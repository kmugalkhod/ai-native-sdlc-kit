"""Out of the loop, end to end: loop.py → pipeline (spec, gate, plan, gate, build, verify, review, assessment) →
merge decision. A scripted stand-in plays `claude`, everything else is real (git, verify, merge, revert).

Checks: trial mode records "would merge" and merges nothing · auto mode merges exactly the verified commit ·
"not confident", a missing assessment, a protected path and a conflict each hand over · a merge that turns main
red is reverted · doctor blocks the loop on a real problem.
python tests/test_outloop.py
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
FAKE = Path(__file__).resolve().parent / "fakes" / "fake_claude.py"
PY = sys.executable
FAILS: list[str] = []


def check(cond: bool, what: str) -> None:
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        FAILS.append(what)


def run(cmd, cwd, env, ok=True):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    if ok and r.returncode:
        raise SystemExit(f"failed: {cmd}\n{r.stdout}\n{r.stderr}")
    return r


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="sdlc-ol-"))
    repo = tmp / "repo"
    repo.mkdir()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "SDLC_CLAUDE_CMD": json.dumps([PY, str(FAKE)])}
    for k in ("SDLC_AGENT", "SDLC_ROLE", "CLAUDECODE"):
        env.pop(k, None)
    g = lambda *a: run(["git", *a], repo, env).stdout.strip()
    g("init", "-q", "-b", "main")
    g("config", "user.email", "t@x")
    g("config", "user.name", "t")
    # the product's test: app.txt must say ok, and a.flag + b.flag together break it (a semantic clash)
    (repo / "check.py").write_text(
        "import os,sys\n"
        "if os.path.exists('app.txt') and open('app.txt').read().strip() != 'ok': sys.exit('app.txt is wrong')\n"
        "if os.path.exists('a.flag') and os.path.exists('b.flag'): sys.exit('a and b clash')\n", encoding="utf-8")
    (repo / "README.md").write_text("line one\n", encoding="utf-8")
    run([PY, str(KIT / "scripts" / "init.py"), "--root", str(repo), "--test", f'"{PY}" check.py'], repo, env)
    g("add", "-A")
    g("commit", "-qm", "init")
    changes = repo / "sdlc" / "changes"

    def new_change(name: str) -> Path:
        c = changes / f"2026-01-01-{name}"
        c.mkdir(parents=True)
        (c / "intent.md").write_text(f"# {name}\n\nStatus: accepted\n", encoding="utf-8")
        g("add", "-A")
        g("commit", "-qm", f"intent {name}")
        return c

    def loop(mode: str, **fake) -> dict:
        e = {**env, **{f"FAKE_{k.upper()}": v for k, v in fake.items()}}
        r = run([PY, ".sdlc/bin/loop.py", "--once", "--no-monitor", "--merge-mode", mode], repo, e, ok=False)
        st = json.loads((repo / ".sdlc" / "state" / "loop.json").read_text(encoding="utf-8"))
        return {"out": r.stdout + r.stderr, "code": r.returncode, "st": st}

    def decision(c: Path) -> dict:
        return json.loads((repo / ".sdlc" / "state" / "merge" / f"{c.name}.json").read_text(encoding="utf-8"))

    # 1. trial: everything is evaluated, nothing is merged
    c1 = new_change("trial")
    r = loop("trial")
    d = decision(c1)
    check(r["st"].get(c1.name, {}).get("result") == "would merge", f"trial: recorded 'would merge' ({r['st'].get(c1.name)})")
    check("app.txt" not in g("ls-tree", "-r", "--name-only", "main"), "trial: main is untouched")
    check(Path(d["facts"].get("evidence", "")).is_file() and d["head"][:12] in d["facts"]["evidence"],
          "trial: verify log kept as evidence for the exact commit")

    # 2. auto: merged exactly the verified head, main verified green afterwards
    c2 = new_change("auto")
    loop("auto", files=json.dumps({"app2.txt": "two\n"}))
    d = decision(c2)
    check(d.get("result") == "merged" and d.get("watch", {}).get("state") == "green", f"auto: merged, main green ({d.get('result')})")
    check("app2.txt" in g("ls-tree", "-r", "--name-only", "main"), "auto: the change is on main")
    check(d["head"] in g("log", "--format=%P", "-1", "main"), "auto: the merge commit's parent is the verified head")

    # 3. not confident → handed over, with the agent's reason
    c3 = new_change("unsure")
    loop("auto", files=json.dumps({"app3.txt": "three\n"}), confident="0")
    d = decision(c3)
    check(d["result"] == "handed over" and any("isn't confident" in x and "empty title" in x for x in d["reasons"]),
          f"not confident: handed over with its reason ({d['reasons']})")
    check("app3.txt" not in g("ls-tree", "-r", "--name-only", "main"), "not confident: nothing merged")

    # 4. no assessment at all → handed over
    c4 = new_change("silent")
    loop("auto", files=json.dumps({"app4.txt": "four\n"}), no_assess="1")
    check(any("didn't report an assessment" in x for x in decision(c4)["reasons"]), "missing assessment: handed over")

    # 5. touching a governance file → handed over, even when confident and green
    c5 = new_change("ci")
    loop("auto", files=json.dumps({".github/workflows/x.yml": "on: push\n"}))
    check(any("protected paths" in x for x in decision(c5)["reasons"]), "protected path: handed over")

    # 6. conflict with main → handed over (branch made by hand, decided through the merge gate CLI)
    c6 = new_change("conflict")
    g("checkout", "-q", "-b", "sdlc/conflict-x")
    (repo / "README.md").write_text("line from the branch\n", encoding="utf-8")
    (c6 / "assessment.json").write_text(json.dumps({"confident": True, "recommendation": "merge", "reason": "",
                                                     "assumptions": []}), encoding="utf-8")
    g("add", "-A")
    g("commit", "-qm", "branch edit")
    g("checkout", "-q", "main")
    (repo / "README.md").write_text("line from main\n", encoding="utf-8")
    g("commit", "-qam", "main edit")
    r = run([PY, ".sdlc/bin/merge_gate.py", "decide", c6.name, "--mode", "auto", "--branch", "sdlc/conflict-x"],
            repo, env, ok=False)
    check(r.returncode == 4 and any("Conflicts with main" in x for x in decision(c6)["reasons"]), "conflict: handed over")
    g("checkout", "-q", "main")

    # 7. green on its own, red once merged → reverted automatically
    c7 = new_change("clash")
    g("checkout", "-q", "-b", "sdlc/clash-x")
    (repo / "b.flag").write_text("b\n", encoding="utf-8")
    (c7 / "assessment.json").write_text(json.dumps({"confident": True, "recommendation": "merge", "reason": "",
                                                     "assumptions": []}), encoding="utf-8")
    g("add", "-A")
    g("commit", "-qm", "add b")
    g("checkout", "-q", "main")
    (repo / "a.flag").write_text("a\n", encoding="utf-8")
    g("add", "-A")
    g("commit", "-qm", "add a")
    run([PY, ".sdlc/bin/merge_gate.py", "decide", c7.name, "--mode", "auto", "--branch", "sdlc/clash-x"], repo, env, ok=False)
    d = decision(c7)
    check(d.get("watch", {}).get("state") == "reverted", f"main went red after the merge → reverted ({d.get('result')})")
    check(not (repo / "b.flag").exists() and run([PY, "check.py"], repo, env, ok=False).returncode == 0,
          "after the revert main is green again")

    # 8. the decision history is kept, and doctor blocks the loop on a real problem (a stale git lock)
    hist = (repo / ".sdlc" / "state" / "merge-decisions.jsonl").read_text(encoding="utf-8").splitlines()
    check(len(hist) >= 7, f"every decision recorded ({len(hist)})")
    lock = repo / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")
    os.utime(lock, (1, 1))
    r = run([PY, ".sdlc/bin/loop.py", "--once", "--no-monitor"], repo, env, ok=False)
    check(r.returncode != 0 and "git locks" in r.stdout + r.stderr, "doctor stops the loop on a stale git lock")
    r = run([PY, ".sdlc/bin/doctor.py", "--fix"], repo, env, ok=False)
    check(not lock.exists(), "doctor --fix removes it")

    shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
