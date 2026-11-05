"""doctor: each problem it should catch is caught, named, and comes with a fix. python tests/test_doctor.py"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[1] / "plugins" / "sdlc"
PY = sys.executable
FAILS: list[str] = []


def check(cond: bool, what: str) -> None:
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        FAILS.append(what)


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="sdlc-dr-"))
    repo = tmp / "repo"
    repo.mkdir()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    run = lambda c: subprocess.run(c, cwd=repo, capture_output=True, text=True, encoding="utf-8", env=env)
    run(["git", "init", "-q", "-b", "main"])
    run(["git", "config", "user.email", "t@x"])
    run(["git", "config", "user.name", "t"])
    run([PY, str(KIT / "scripts" / "init.py"), "--root", str(repo), "--test", f'"{PY}" -c "print(1)"'])
    run(["git", "add", "-A"])
    run(["git", "commit", "-qm", "init"])
    doc = lambda: {c["name"]: c for c in json.loads(run([PY, ".sdlc/bin/doctor.py", "--json"]).stdout)}

    d = doc()
    check(d["config"]["status"] == "ok" and d["verify tools"]["status"] == "ok", "a fresh project: config and tools ok")
    check(d["ignored folders"]["status"] == "ok", "kit state, worktrees and evidence are git-ignored")
    check(d["permissions"]["status"] == "warn" and "team.py allow" in d["permissions"]["fix"],
          "missing teammate permissions: warned, with the fix")
    run([PY, ".sdlc/bin/team.py", "allow"])
    check(doc()["permissions"]["status"] == "ok", "after team.py allow: ok")

    cfg = json.loads((repo / ".sdlc" / "config.json").read_text(encoding="utf-8"))
    cfg["verify"]["lint"] = "notarealtool123 check ."
    (repo / ".sdlc" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    d = doc()
    check(d["verify tools"]["status"] == "fail" and "notarealtool123" in d["verify tools"]["detail"],
          "a verify tool that isn't installed: named as a problem")
    (repo / ".sdlc" / "config.json").write_text("{ broken", encoding="utf-8")
    r = run([PY, ".sdlc/bin/doctor.py"])
    check(r.returncode == 1 and "config" in r.stdout, "a broken config.json: problem, exit 1")
    shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
