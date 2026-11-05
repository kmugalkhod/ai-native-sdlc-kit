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

# Repo files the agent must never change itself: its own gates, state and audit trail, and what humans own.
SELF_PROTECTED = [".sdlc/config.json", ".sdlc/state/**", ".sdlc/bin/**", ".sdlc/audit.jsonl", "sdlc/MISSION.md",
                  "sdlc/defects.json", ".ignore"]
# Hidden holdout scenarios: no builder may read them; only the holdout writer / verifier agents.
HOLDOUT_DIR = "sdlc/holdout"
HOLDOUT_AGENTS = {"holdout-writer", "holdout-verifier", "sdlc:holdout-writer", "sdlc:holdout-verifier"}
GIT_PRINTS = {"show", "log", "diff", "grep", "blame", "cat-file", "whatchanged"}  # read-only ones
HELPER_RE = re.compile(r"^\s*(python3?|py)(\s+-\w+)*\s+\.sdlc/bin/[\w-]+\.py\b")
WRITE_VERB_RE = re.compile(
    r"(^|\s)(rm|mv|cp|tee|truncate|chmod|chown|ln|dd|install|unlink|shred)(\s|$)|"
    r"\bsed\s+(-\w*i|--in-place)|\bperl\s+-\w*i|(?<![0-9&>-])>{1,2}(?!&)|\bgit\s+(checkout|restore|rm|mv)\b|\bset-content\b|\bout-file\b",
    re.I,
)
GOV_RE = re.compile(r"\.sdlc[/\\](config\.json|state|bin|audit\.jsonl)")
REDIRECT_RE = re.compile(r"(?<![0-9&>-])>{1,2}\|?\s*([^\s;|&)]+)")
VERB_RE = re.compile(
    r"(^|\s)(rm|mv|cp|tee|truncate|chmod|chown|ln|dd|install|unlink|shred)(\s|$)|"
    r"\bsed\s+(-\w*i|--in-place)|\bperl\s+-\w*i|\bgit\s+(checkout|restore|rm|mv)\b|\bset-content\b|\bout-file\b",
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


# ---------------------------------------------------------------- holdout fence
def holdout_ok(payload: dict) -> bool:
    """Only the holdout writer / verifier see the scenarios: launched with SDLC_HOLDOUT_ACCESS=1 by the pipeline,
    or a subagent of that type."""
    return os.environ.get("SDLC_HOLDOUT_ACCESS") == "1" or str(payload.get("agent_type") or "") in HOLDOUT_AGENTS


def in_holdout(root: Path, path: str) -> bool:
    if not path:
        return False
    rel = rel_to_root(root, str(path)).rstrip("/")
    return rel == HOLDOUT_DIR or rel.startswith(HOLDOUT_DIR + "/") or bool(re.search(r"(^|[/\\])holdout([/\\]|$)", str(path)))


def holdout_lines(root: Path) -> set[str]:
    """Distinctive lines of every scenario: if one shows up in a tool's output, a builder has seen it."""
    out = set()
    d = root / HOLDOUT_DIR
    for f in d.rglob("*") if d.is_dir() else []:
        if f.is_file():
            for ln in f.read_text(encoding="utf-8", errors="replace").splitlines():
                ln = ln.strip().lstrip("-*#> ").strip()
                if len(ln) >= 30:
                    out.add(ln)
    return out


def exposed(root: Path, text: str) -> list[str]:
    return [ln for ln in holdout_lines(root) if ln in text][:3]


def holdout_deny(root: Path, what: str, **fields) -> None:
    block(root, f"{what} would show the hidden holdout scenarios ({HOLDOUT_DIR}/). They are an exam no builder may "
                "see; build from intent.md, spec.md and plan.md instead.", **fields)


def pre_read(root: Path, cfg: dict, payload: dict) -> None:
    if holdout_ok(payload) or not (root / HOLDOUT_DIR).is_dir():
        return
    ti = payload.get("tool_input") or {}
    for k in ("file_path", "notebook_path", "path", "pattern", "glob"):
        v = ti.get(k)
        if v and (in_holdout(root, v) or (k in ("pattern", "glob") and "holdout" in str(v).lower()
                                          and payload.get("tool_name") == "Glob")):
            holdout_deny(root, f"{payload.get('tool_name') or 'This read'} of {v}", path=str(v))


def post_read(root: Path, cfg: dict, payload: dict) -> None:
    """A leak the fence did not foresee is still counted: scenario text in any tool output is recorded."""
    if holdout_ok(payload) or not (root / HOLDOUT_DIR).is_dir():
        return
    hits = exposed(root, json.dumps(payload.get("tool_response") or payload.get("tool_output") or "", ensure_ascii=False))
    if hits:
        common = git(root, "rev-parse", "--git-common-dir") or ".git"
        log = (root / common if not Path(common).is_absolute() else Path(common)) / "sdlc-holdout-exposures.jsonl"
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                "tool": payload.get("tool_name"), "cwd": payload.get("cwd"),
                                "branch": git(Path(payload.get("cwd") or root), "rev-parse", "--abbrev-ref", "HEAD"),
                                "lines": len(hits)}) + "\n")
        audit(root, "holdout-exposure", tool=payload.get("tool_name"))


def bash_holdout(root: Path, payload: dict, segs: list[str]) -> None:
    if holdout_ok(payload) or not (root / HOLDOUT_DIR).is_dir():
        return
    cwd = Path(payload.get("cwd") or root)
    for seg in segs:
        if re.search(r"(^|[\s'\"=/\\])(sdlc[/\\])?holdout([/\\*'\"\s]|$)", seg):
            holdout_deny(root, "This command", command=seg)
        t = tokens(seg)
        if len(t) >= 2 and t[0] == "git" and (set(t[1:3]) & GIT_PRINTS):
            # git is asked first: run the read-only command ourselves and look for scenario text in what it prints
            try:
                r = subprocess.run(t, cwd=cwd, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=15,
                                   env={**os.environ, "GIT_PAGER": "cat", "PAGER": "cat"})
                if exposed(root, r.stdout):
                    holdout_deny(root, f"`{seg[:60]}`", command=seg)
            except (subprocess.TimeoutExpired, OSError):
                pass


# ---------------------------------------------------------------- pre-edit
def pre_edit(root: Path, cfg: dict, payload: dict) -> None:
    ti = payload.get("tool_input") or {}
    path = ti.get("file_path") or ti.get("notebook_path") or ""
    if not path:
        return
    rel = rel_to_root(root, path)
    if in_holdout(root, path) and not holdout_ok(payload) and (root / HOLDOUT_DIR).is_dir():
        holdout_deny(root, f"Writing {rel}", path=rel)
    if in_holdout(root, path) and holdout_ok(payload):
        return  # the holdout writer owns its folder

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
    bash_holdout(root, payload, segs)

    # 1. Governance files: the agent cannot rewrite its own gates or audit trail from the shell. Only a write
    #    whose TARGET is a governance path counts: `python .sdlc/bin/x.py > /tmp/log` is fine.
    for seg in segs:
        targets = REDIRECT_RE.findall(seg)
        bare = re.sub(r"^[\s(]*((nohup|exec|time|env)\s+|[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*", "", seg)
        if HELPER_RE.match(bare) and not any(GOV_RE.search(t) for t in targets):
            continue  # the helper CLI enforces its own human-only actions
        if not GOV_RE.search(seg):
            continue
        verb = VERB_RE.search(seg)
        after = seg[verb.end():] if verb else ""
        if verb and (verb.group(2) or "").lower() in ("cp", "install", "ln"):
            args = [t for t in tokens(after) if not t.startswith("-")]
            after = args[-1] if args else ""  # copying FROM a governance file is fine; only the destination counts
        if any(GOV_RE.search(t) for t in targets) or (verb and GOV_RE.search(after)):
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


# ---------------------------------------------------------------- activity (agent teams)
WT_RE = re.compile(r"\.sdlc[/\\]worktrees[/\\]([A-Za-z0-9_-]+)")
AS_RE = re.compile(r"--as\s+([A-Za-z0-9_-]+)")


def activity(root: Path, cfg: dict, payload: dict) -> None:
    """Show what each agent-team teammate is doing on the live board. Silent and best-effort: never blocks."""
    ti = payload.get("tool_input") or {}
    tool = payload.get("tool_name") or ""
    where = " ".join(str(x) for x in (ti.get("file_path"), ti.get("command"), ti.get("url"), payload.get("cwd")) if x)
    m = AS_RE.search(ti.get("command") or "") or WT_RE.search(where)
    if not m or m.group(1) in ("integration", "check"):
        return
    agent = m.group(1)
    if tool == "Bash":
        cmd = re.sub(r'^\s*cd\s+("[^"]*"|\S+)\s*&&\s*', "", " ".join((ti.get("command") or "").split()))
        what = "$ " + cmd[:110]
    elif tool in ("Edit", "Write", "MultiEdit"):
        what = f"{tool.lower()} " + re.split(r"worktrees[/\\][^/\\]+[/\\]", ti.get("file_path", ""))[-1]
    elif tool.startswith("mcp__playwright__"):
        what = f"browser: {tool.split('__')[-1].replace('browser_', '')} {str(ti.get('url') or ti.get('element') or '')[:60]}"
    else:
        return
    if "board.py" in what:
        return
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from board import Board  # noqa: E402
        b = Board(root / ".sdlc" / "state" / "board.db")
        a = next((x for x in b.agents() if x["name"] == agent), None)
        if not a:
            return
        b.upsert_agent(agent, activity=what.strip())
        b.event(a.get("item_key"), agent, "activity", what.strip())
    except Exception:
        pass


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
    {"pre-edit": pre_edit, "pre-bash": pre_bash, "post-edit": post_edit, "activity": activity,
     "pre-read": pre_read, "post-read": post_read}.get(
        mode, lambda *a: None)(root, cfg, payload)
    sys.exit(0)


if __name__ == "__main__":
    main()
