#!/usr/bin/env python3
"""Scaffold the AI-Native SDLC into a repo (called by /sdlc:init). Never overwrites existing files.

  python init.py --root . [--ci github|gitlab|none] [--setup CMD] [--build CMD] [--test CMD] [--lint CMD]
                 [--format CMD] [--protected GLOB ...] [--tracker jira|gitlab|github|none] [--upgrade-bin]

Once .sdlc/config.json exists only a human (interactive terminal) can regenerate it with --force-config,
because the config defines the agent's own gates.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
TEMPLATES = PLUGIN / "templates"
BIN_FILES = ["sdlc_core.py", "sdlc.py", "pipeline.py", "evals.py", "monitor.py", "loop.py",
             "board.py", "team.py", "trackers.py", "board_server.py"]
CI_FILES = {
    "github": [".github/workflows/agent-evals.yml", ".github/workflows/claude-review.yml",
               ".github/workflows/sdlc-loop.yml", ".github/workflows/sdlc-monitor.yml"],
    "gitlab": [".gitlab/sdlc.gitlab-ci.yml"],
    "none": [],
}
COMMON = [
    "CLAUDE.md", "REVIEW.md", ".claude/settings.json",
    ".sdlc/.gitignore", ".sdlc/templates/intent.md", ".sdlc/templates/spec.md",
    ".sdlc/templates/plan.md", ".sdlc/templates/review.md",
    "sdlc/changes/.gitkeep", "sdlc/lessons/README.md",
    "sdlc/monitor/bands.yaml", "sdlc/monitor/sample_series.csv",
    "evals/cases/verify-before-done.json", "evals/README.md",
]


def copy(rel: str, root: Path, created: list, skipped: list, src_rel: str | None = None) -> None:
    src, dst = TEMPLATES / (src_rel or rel), root / rel
    if dst.exists():
        skipped.append(rel); return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    created.append(rel)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--ci", choices=list(CI_FILES), default="none")
    ap.add_argument("--setup", default="", help="installs dependencies, e.g. pip install -r requirements.txt / npm ci")
    ap.add_argument("--build", default="")
    ap.add_argument("--test", default="")
    ap.add_argument("--lint", default="")
    ap.add_argument("--format", default="", help="formatter run after each edit; {file} = edited path")
    ap.add_argument("--protected", nargs="*", default=[])
    ap.add_argument("--tracker", default="internal", choices=["internal", "jira", "linear"])
    ap.add_argument("--qa-start", default="", help="command that starts the app for QA, with {port}")
    ap.add_argument("--developers", type=int, default=2)
    ap.add_argument("--qa-agents", type=int, default=1)
    ap.add_argument("--vcs", default="auto")
    ap.add_argument("--upgrade-bin", action="store_true")
    ap.add_argument("--force-config", action="store_true")
    a = ap.parse_args()

    root = Path(a.root).resolve()
    created, skipped = [], []

    cfg_path = root / ".sdlc" / "config.json"
    if cfg_path.exists() and a.force_config:
        if not sys.stdin.isatty() or os.environ.get("CLAUDECODE"):
            sys.exit("--force-config rewrites the agent's own gates; run it yourself in a terminal.")
    if not cfg_path.exists() or a.force_config:
        cfg = json.loads((TEMPLATES / ".sdlc" / "config.json").read_text(encoding="utf-8"))
        cfg["verify"] = {"setup": a.setup, "build": a.build, "test": a.test, "lint": a.lint}
        cfg["format_cmd"] = a.format
        cfg["protected_paths"] = sorted(set(cfg.get("protected_paths", []) + a.protected))
        cfg["tracker"]["type"] = a.tracker
        cfg["team"]["qa"]["start_cmd"] = a.qa_start
        cfg["team"]["developers"], cfg["team"]["qa_agents"] = a.developers, a.qa_agents
        cfg["vcs"] = a.vcs if a.vcs != "auto" else {"github": "github", "gitlab": "gitlab"}.get(a.ci, "auto")
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        created.append(".sdlc/config.json")
    else:
        skipped.append(".sdlc/config.json")

    for rel in COMMON + CI_FILES[a.ci]:
        copy(rel, root, created, skipped)

    bin_dir = root / ".sdlc" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for f in BIN_FILES:
        dst = bin_dir / f
        if dst.exists() and not a.upgrade_bin:
            skipped.append(f".sdlc/bin/{f}"); continue
        shutil.copy2(PLUGIN / "scripts" / f, dst)
        created.append(f".sdlc/bin/{f}")

    # keep installed dependencies out of commits (the headless loop commits with `git add -A`)
    gi = root / ".gitignore"
    have = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    missing = [x for x in (".venv/", "venv/", "node_modules/", "__pycache__/", ".pytest_cache/") if x not in have]
    if missing:
        with open(gi, "a", encoding="utf-8") as f:
            f.write(("\n" if have and have[-1] else "") + "# added by sdlc init\n" + "\n".join(missing) + "\n")
        created.append(".gitignore (+" + ", ".join(missing) + ")")

    print(json.dumps({"created": created, "skipped_existing": skipped}, indent=2))


if __name__ == "__main__":
    main()
