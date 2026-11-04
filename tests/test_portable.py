"""Commands from .sdlc/config.json must work on every OS without the user editing them.

Real npm and venv, no mocks: `npm --prefix DIR install` (fails as written on Windows), `.venv/bin/...` paths (wrong on
Windows), and the setup cache (second verify must skip the install).  python tests/test_portable.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[1] / "plugins" / "sdlc"
sys.path.insert(0, str(KIT / "scripts"))
import sdlc_core  # noqa: E402

FAILS: list[str] = []


def check(cond: bool, what: str) -> None:
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        FAILS.append(what)


def verify(repo: Path, *steps: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(KIT / "scripts" / "sdlc.py"), "verify", *steps], cwd=repo,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def main() -> None:
    pc = sdlc_core.portable_cmd
    check("npm --prefix" not in pc("npm --prefix frontend install --no-audit"), "npm --prefix install is rewritten")
    check(pc("npm --prefix frontend run build") == "npm --prefix frontend run build", "npm --prefix run is left alone")
    check("install" in pc("npm install --prefix web") and "--prefix" not in pc("npm install --prefix web"),
          "npm install --prefix DIR form is rewritten")
    if os.name == "nt":
        check(pc(".venv/bin/python -m pytest") == ".venv\\Scripts\\python -m pytest", "Windows venv path rewritten")

    tmp = Path(tempfile.mkdtemp(prefix="sdlc-port-"))
    repo = tmp / "repo"
    (repo / "frontend").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / ".sdlc").mkdir()
    (repo / "requirements.txt").write_text("", encoding="utf-8")
    (repo / "frontend" / "package.json").write_text(json.dumps(
        {"name": "f", "version": "1.0.0", "private": True, "dependencies": {"left-pad": "1.3.0"}}), encoding="utf-8")
    setup = "python -m venv .venv && .venv/bin/python -c \"print('venv ok')\" && npm --prefix frontend install --no-audit --no-fund"
    if os.name != "nt" and not shutil.which("python"):
        setup = setup.replace("python -m venv", "python3 -m venv", 1)
    test = "node -e \"require('./frontend/node_modules/left-pad');console.log('dep ok')\""
    (repo / ".sdlc" / "config.json").write_text(json.dumps(
        {"verify": {"setup": setup, "build": "", "test": test, "lint": ""}}), encoding="utf-8")
    if not shutil.which("npm"):
        print("SKIP real npm checks: npm not on PATH")
    else:
        r = verify(repo)
        print(r.stdout[-800:], r.stderr[-400:])
        check(r.returncode == 0, "verify is green with npm --prefix + .venv/bin in the config (as written)")
        check("dep ok" in r.stdout, "the frontend dependency was installed in frontend/")
        r2 = verify(repo)
        check("setup: SKIP" in r2.stdout and r2.returncode == 0, "second verify skips the unchanged install")
        (repo / "frontend" / "package.json").write_text(json.dumps(
            {"name": "f", "version": "1.0.1", "private": True, "dependencies": {"left-pad": "1.3.0"}}), encoding="utf-8")
        r3 = verify(repo)
        check("setup: SKIP" not in r3.stdout and r3.returncode == 0, "a changed manifest reinstalls")
    shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
