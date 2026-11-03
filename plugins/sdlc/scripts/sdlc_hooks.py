"""Deterministic gates for the AI-Native SDLC (playbook: hooks as build-time guardrails + approval gates).

Usage (from hooks/hooks.json):  sdlc_hooks.py pre-edit | pre-bash | post-edit
Reads the hook payload as JSON on stdin. Exit 2 blocks the tool call and sends stderr to Claude.
No-op unless the repo has .sdlc/config.json (created by /sdlc:init).
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sdlc_core import audit, find_root, git, load_config, matches_any, read_state, rel_to_root  # noqa: E402

# Repo files the agent must never change itself: its own gates, state and audit trail.
SELF_PROTECTED = [".sdlc/config.json", ".sdlc/state/**", ".sdlc/bin/**", ".sdlc/audit.jsonl"]
HELPER_RE = re.compile(r"^\s*(python3?|py)(\s+-\w+)*\s+\.sdlc/bin/[\w-]+\.py\b")
WRITE_VERB_RE = re.compile(
    r"(^|\s)(rm|mv|cp|tee|truncate|chmod|chown|ln|dd|install|unlink|shred)(\s|$)|"
    r"\bsed\s+(-\w*i|--in-place)|\bperl\s+-\w*i|(?<![0-9&>-])>{1,2}(?!&)|\bgit\s+(checkout|restore|rm|mv)\b|\bset-content\b|\bout-file\b",
    re.I,
)
SECRET_PATTERNS = {
    "AWS access key": r"\bA(KIA|SIA)[0-9A-Z]{16}\b",
    "private key": r"-----BEGIN (RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY",
    "GitHub token": r"\bgh[pousr]_[A-Za-z0-9]{36,}\b",
    "GitLab token": r"\bglpat-[A-Za-z0-9_\-]{20,}\b",
    "Slack token": r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b",
    "Anthropic key": r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b",
    "OpenAI-style key": r"\bsk-(proj-)?[A-Za-z0-9]{32,}\b",
    "AWS secret key assignment": r"aws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}",
    "generic password assignment": r"(?i)\b(password|passwd|secret|api[_-]?key)\s*[=:]\s*['\"][^'\"\s$<{]{12,}['\"]",
}


def block(root: Path, reason: str, **fields) -> None:
    audit(root, "block", reason=reason, **fields)
    print(f"[sdlc gate] {reason}", file=sys.stderr)
    sys.exit(2)


def ask(root: Path, reason: str, **fields) -> None:
    audit(root, "ask", reason=reason, **fields)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "ask", "permissionDecisionReason": f"[sdlc gate] {reason}"}}))
    sys.exit(0)


def segments(cmd: str) -> list[str]:
    return [s.strip() for s in re.split(r"&&|\|\||;|\n|\|(?!\|)", cmd) if s.strip()]


def tokens(seg: str) -> list[str]:
    try:
        return shlex.split(seg, posix=True)
    except ValueError:
        return seg.split()


def fix_mode(root: Path) -> dict | None:
    return read_state(root, "fix-mode.json")


# ---------------------------------------------------------------- pre-edit
def pre_edit(root: Path, cfg: dict, payload: dict) -> None:
    ti = payload.get("tool_input") or {}
    path = ti.get("file_path") or ti.get("notebook_path") or ""
    if not path:
        return
    rel = rel_to_root(root, path)

    hit = matches_any(rel, SELF_PROTECTED)
    if hit:
        block(root, f"{rel} is a governance file (matches {hit}). A human edits it by hand; ask them.", path=rel)

    hit = matches_any(rel, cfg.get("protected_paths", []))
    if hit:
        block(root, f"{rel} is a protected path (matches '{hit}' in .sdlc/config.json protected_paths). "
                    "Leave it unchanged or ask the owner.", path=rel)

    fm = fix_mode(root)
    if fm:
        locked = list(fm.get("locked_files", [])) + list(cfg.get("test_globs", []))
        hit = matches_any(rel, locked)
        if hit:
            block(root, f"Fix mode is on (since {fm.get('since')}): test files are locked so the check cannot be "
                        f"weakened. {rel} matches '{hit}'. Fix the code, not the test.", path=rel)

    if cfg.get("secret_scan", True) and not matches_any(rel, cfg.get("secret_scan_exclude", [])):
        text = "\n".join(filter(None, [ti.get("content"), ti.get("new_string"), ti.get("new_source"),
                                       *[e.get("new_string", "") for e in ti.get("edits", []) or []]]))
        for name, pat in SECRET_PATTERNS.items():
            if re.search(pat, text):
                block(root, f"Possible {name} in the content for {rel}. Use an env var or secret store reference "
                            "instead; never put credentials in the diff.", path=rel, kind=name)


# ---------------------------------------------------------------- pre-bash
def release_approval(root: Path, cfg: dict) -> str | None:
    env_name = cfg["prod_gate"].get("approval_env", "RELEASE_APPROVAL")
    if os.environ.get(env_name):
        return f"env:{os.environ[env_name]}"
    st = read_state(root, "release-approval.json")
    if st:
        ttl = int(cfg["prod_gate"].get("approval_ttl_minutes", 120)) * 60
        try:
            granted = datetime.strptime(st["granted_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        except Exception:
            granted = 0
        if time.time() - granted < ttl:
            return f"{st.get('approver')}:{st.get('reference')}"
    return None


def pre_bash(root: Path, cfg: dict, payload: dict) -> None:
    cmd = (payload.get("tool_input") or {}).get("command", "") or ""
    segs = segments(cmd)

    # 1. Governance files: the agent cannot rewrite its own gates or audit trail from the shell.
    for seg in segs:
        if HELPER_RE.match(seg):
            continue  # the helper CLI enforces its own human-only actions
        if re.search(r"\.sdlc[/\\](config\.json|state|bin|audit\.jsonl)", seg) and WRITE_VERB_RE.search(seg):
            block(root, "This command would change .sdlc governance files (config/state/bin/audit). "
                        "A human does that by hand.", command=cmd)

    # 2. Fix mode: no shell writes to test files either.
    fm = fix_mode(root)
    if fm:
        locked = list(fm.get("locked_files", [])) + list(cfg.get("test_globs", []))
        for seg in segs:
            if not WRITE_VERB_RE.search(seg):
                continue
            for tok in tokens(seg):
                if "/" in tok or "." in tok:
                    hit = matches_any(rel_to_root(root, tok), locked)
                    if hit:
                        block(root, f"Fix mode is on: shell writes to test files are blocked ({tok} matches '{hit}').",
                              command=cmd)

    # 2b. Human-only board actions: an agent session (SDLC_AGENT set by the team lead) cannot approve a design,
    #     even by clearing the variable inline.
    if os.environ.get("SDLC_AGENT") and re.search(r"board\.py\s+(design-(approve|changes)|resume)\b", cmd):
        block(root, "Only the human approves a design or resumes an escalated task. Ask them on the board instead.",
              command=cmd)

    # 3. No direct push to protected branches: everything the agent writes arrives as a PR.
    protected = set(cfg.get("protected_branches", []))
    for seg in segs:
        t = tokens(seg)
        if len(t) >= 2 and t[0] == "git" and "push" in t[1:3]:
            args = [a for a in t[t.index("push") + 1:] if not a.startswith("-")]
            refs = args[1:] if args else []
            targets = {r.split(":")[-1].replace("refs/heads/", "").lstrip("+") for r in refs}
            if not refs:
                targets = {git(root, "rev-parse", "--abbrev-ref", "HEAD")}
            bad = targets & protected
            if bad:
                block(root, f"Direct push to protected branch {sorted(bad)} is not allowed. Push a feature branch "
                            "and open a PR/MR; branch protection and a code owner decide the merge.", command=cmd)

    # 4. Production gate: the agent may act up to the production gate and cannot pass it.
    for pat in cfg["prod_gate"].get("patterns", []):
        if re.search(pat, cmd, re.I):
            approval = release_approval(root, cfg)
            if approval:
                audit(root, "allow", gate="production", approval=approval, command=cmd)
                return
            reason = ("Production action needs a release authorization. Release manager runs "
                      "`python .sdlc/bin/sdlc.py approve-release <ticket>` in their own terminal (or sets "
                      f"{cfg['prod_gate'].get('approval_env', 'RELEASE_APPROVAL')}), then retry.")
            if cfg["prod_gate"].get("mode", "block") == "ask":
                ask(root, reason, gate="production", command=cmd)
            block(root, reason, gate="production", command=cmd)


# ---------------------------------------------------------------- post-edit
def post_edit(root: Path, cfg: dict, payload: dict) -> None:
    ti = payload.get("tool_input") or {}
    path = ti.get("file_path") or ""
    if not path:
        return
    rel = rel_to_root(root, path)
    if rel.startswith("/") or rel.startswith(".sdlc/") or rel.endswith(".md"):
        return
    for key, feedback in (("format_cmd", False), ("lint_on_edit_cmd", True)):
        tmpl = (cfg.get(key) or "").strip()
        if not tmpl:
            continue
        cmd = tmpl.replace("{file}", shlex.quote(rel))
        try:
            r = subprocess.run(cmd, shell=True, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=100)
        except subprocess.TimeoutExpired:
            print(f"[sdlc] {key} timed out: {cmd}", file=sys.stderr)
            continue
        if r.returncode != 0 and feedback:
            out = (r.stdout + r.stderr).strip()[-3000:]
            print(f"[sdlc] lint failed for {rel} — fix before moving on:\n{out}", file=sys.stderr)
            sys.exit(2)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    root = find_root(payload.get("cwd"))
    if not root:
        sys.exit(0)  # repo not initialised for the SDLC kit
    cfg = load_config(root)
    {"pre-edit": pre_edit, "pre-bash": pre_bash, "post-edit": post_edit}.get(mode, lambda *a: None)(root, cfg, payload)
    sys.exit(0)


if __name__ == "__main__":
    main()
