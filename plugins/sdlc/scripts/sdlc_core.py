"""Shared helpers for the AI-Native SDLC kit: config, glob matching, audit log, change discovery.

Used by the plugin hooks and by the repo-local CLI in .sdlc/bin/. Standard library only.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CONFIG_REL = ".sdlc/config.json"

DEFAULTS: dict = {
    "changes_dir": "sdlc/changes",
    "lessons_dir": "sdlc/lessons",
    "protected_paths": [],
    "test_globs": [
        "tests/**", "test/**", "**/__tests__/**",
        "**/test_*.py", "**/*_test.py", "**/*_test.go",
        "**/*.test.*", "**/*.spec.*", "**/src/test/**", "**/itest/**",
    ],
    "verify": {"build": "", "test": "", "lint": ""},
    "format_cmd": "",
    "lint_on_edit_cmd": "",
    "prod_gate": {
        "patterns": [r"\bdeploy\b.*\bprod(uction)?\b", r"\bhelm\b.*\b(upgrade|install)\b.*\bprod", r"\bkubectl\b.*\b(apply|delete|rollout)\b.*\bprod"],
        "approval_env": "RELEASE_APPROVAL",
        "approval_ttl_minutes": 120,
    },
    "protected_branches": ["main", "master"],
    "secret_scan": True,
    "secret_scan_exclude": [],
    "tracker": {"type": "none", "url_template": ""},
    "vcs": "auto",
    "models": {
        "spec": "sonnet", "plan": "sonnet", "build": "sonnet",
        "review": "sonnet", "gate": "sonnet", "triage": "sonnet", "evals": "sonnet",
    },
    "pipeline": {"commit": True, "branch_prefix": "sdlc/", "open_pr": False, "max_fix_rounds": 3},
    "evals": {"dir": "evals/cases", "threshold": 0.9},
}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_root(start: str | os.PathLike | None = None) -> Path | None:
    """Walk up from start (or cwd) to the first directory holding .sdlc/config.json."""
    p = Path(start or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
    for d in [p, *p.parents]:
        if (d / CONFIG_REL).is_file():
            return d
    return None


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load_config(root: Path) -> dict:
    try:
        user = json.loads((root / CONFIG_REL).read_text(encoding="utf-8"))
    except Exception as e:  # broken config must not silently disable gates
        print(f"sdlc: cannot parse {CONFIG_REL}: {e}; using defaults", file=sys.stderr)
        user = {}
    return _merge(DEFAULTS, user)


def glob_to_regex(pattern: str) -> re.Pattern:
    """Gitignore-ish glob: ** spans directories, * and ? stay within a segment."""
    i, out = 0, ""
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"; i += 3; continue
        if pattern.startswith("**", i):
            out += ".*"; i += 2; continue
        out += {"*": "[^/]*", "?": "[^/]"}.get(c, re.escape(c)); i += 1
    return re.compile("^" + out + "$")


def matches_any(rel_path: str, patterns: list[str]) -> str | None:
    rel = rel_path.replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    for pat in patterns or []:
        if glob_to_regex(pat).match(rel):
            return pat
    return None


def rel_to_root(root: Path, path: str) -> str:
    p = Path(path)
    if not p.is_absolute():
        p = root / p
    try:
        return p.resolve().relative_to(root).as_posix()
    except ValueError:
        return p.as_posix()  # outside the repo


def audit(root: Path, event: str, **fields) -> None:
    """Append one JSON line to .sdlc/audit.jsonl (who/what/when for gate decisions)."""
    try:
        line = {"ts": utcnow(), "event": event, "user": os.environ.get("USER") or os.environ.get("USERNAME"), **fields}
        with open(root / ".sdlc" / "audit.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
    except Exception:
        pass


def state_path(root: Path, name: str) -> Path:
    return root / ".sdlc" / "state" / name


def read_state(root: Path, name: str) -> dict | None:
    p = state_path(root, name)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
    except Exception:
        return None


def git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        return ""


def changes(root: Path, cfg: dict) -> list[Path]:
    d = root / cfg["changes_dir"]
    return sorted([p for p in d.iterdir() if p.is_dir()]) if d.is_dir() else []


def header_field(md_path: Path, field: str) -> str | None:
    """Read 'Field: value' from the first 15 lines of an artifact (e.g. Status: accepted)."""
    if not md_path.is_file():
        return None
    for line in md_path.read_text(encoding="utf-8", errors="ignore").splitlines()[:15]:
        m = re.search(rf"\b{re.escape(field)}:\s*[*`]*([A-Za-z0-9][\w-]*)", line, re.I)
        if m:
            return m.group(1).lower()
    return None


def stage_of(change_dir: Path) -> str:
    """Infer where a change sits in the loop from which artifacts exist and their Status lines."""
    i, s, p = (change_dir / f for f in ("intent.md", "spec.md", "plan.md"))
    if (change_dir / "review.md").is_file():
        return "review"
    if p.is_file():
        st = header_field(p, "Status") or "draft"
        return "build" if st in ("accepted", "approved", "in-progress", "implemented") else "plan"
    if s.is_file():
        st = header_field(s, "Status") or "draft"
        return "plan-ready" if st in ("accepted", "approved") else "design"
    if i.is_file():
        st = header_field(i, "Status") or "draft"
        if st == "rejected":
            return "rejected"
        return "design-ready" if st in ("accepted", "approved") else "intent"
    return "empty"
