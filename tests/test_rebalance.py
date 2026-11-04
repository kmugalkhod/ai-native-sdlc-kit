"""A free developer takes work another developer was given but has not started — like a real team lead would.

dev-1 gets a 3-task story while dev-2 is busy. dev-2 finishes; dev-1 has only started the first task. The lead must
move the two untouched tasks to dev-2, tell dev-1 to skip them, and the run must still finish with everything merged.
python tests/test_rebalance.py
"""
from __future__ import annotations

import json
import os
import re
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


def run(cmd, cwd, env, ok=True):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    if ok and r.returncode:
        raise SystemExit(f"failed: {cmd}\n{r.stdout}\n{r.stderr}")
    return r


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="sdlc-rb-"))
    repo = tmp / "repo"
    repo.mkdir()
    env = {**os.environ, "SDLC_BOARD_DB": str(repo / ".sdlc" / "state" / "board.db"), "PYTHONIOENCODING": "utf-8"}
    env.pop("SDLC_AGENT", None)
    run(["git", "init", "-q", "-b", "main"], repo, env)
    run(["git", "config", "user.email", "t@x"], repo, env)
    run(["git", "config", "user.name", "t"], repo, env)
    run([PY, str(KIT / "scripts" / "init.py"), "--root", str(repo), "--developers", "2", "--qa-agents", "1"], repo, env)
    ch = repo / "sdlc" / "changes" / "2026-01-01-api"
    ch.mkdir(parents=True)
    (ch / "intent.md").write_text("Status: accepted\n", encoding="utf-8")
    t = lambda i, f: {"id": i, "title": f"task {i}", "files": [f], "acceptance": ["ok"], "qa": "check", "ui": False,
                      "depends_on": []}
    (ch / "breakdown.json").write_text(json.dumps({"epic": {"title": "API"}, "ui": False, "stories": [
        {"id": "S1", "title": "Providers", "tasks": [t("T1", "app/a.py"), t("T2", "app/b.py"), t("T3", "app/c.py")]},
        {"id": "S2", "title": "Admin", "tasks": [t("T4", "app/d.py")]}]}), encoding="utf-8")
    run(["git", "add", "-A"], repo, env)
    run(["git", "commit", "-qm", "init"], repo, env)
    team, board = [PY, ".sdlc/bin/team.py"], [PY, ".sdlc/bin/board.py"]
    step = lambda cmd, *a: json.loads(run(team + [cmd, "api", "--simulate", *a], repo, env).stdout)
    wt = lambda text: Path(re.search(r"YOUR WORKTREE: (.+)", text).group(1).strip())

    def build(agent, keys, text):
        w = wt(text)
        for k in keys:
            f = w / "app" / f"{ {'T-1': 'a', 'T-2': 'b', 'T-3': 'c', 'T-4': 'd'}[k] }.py".replace(" ", "")
            f.parent.mkdir(exist_ok=True)
            f.write_text(f"# {k} by {agent}\n", encoding="utf-8")
            run(["git", "add", "-A"], w, env)
            run(["git", "commit", "-qm", f"{k}: work"], w, env)
            run(board + ["--as", agent, "--role", "developer", "submit", k, "done"], repo, env)

    out = step("prepare")
    a = {x["agent"]: x for x in out["assignments"]}
    check(a.get("dev-1", {}).get("keys") == ["T-1", "T-2", "T-3"], f"dev-1 got the whole story ({a.get('dev-1', {}).get('keys')})")
    check(a.get("dev-2", {}).get("keys") == ["T-4"], "dev-2 got the other story")
    d1 = Path(a["dev-1"]["file"]).read_text(encoding="utf-8")
    w1 = wt(d1)
    build("dev-2", ["T-4"], Path(a["dev-2"]["file"]).read_text(encoding="utf-8"))
    # dev-1 has not even touched a file yet: it is on T-1, so T-2 and T-3 can still go to the idle dev-2

    out = step("next", "--done", "dev-2")
    a = {x["agent"]: x for x in out["assignments"]}
    check(set(a.get("dev-2", {}).get("keys", [])) == {"T-2", "T-3"}, f"idle dev-2 took the untouched T-2, T-3 ({a.get('dev-2', {}).get('keys')})")
    check(a.get("dev-1", {}).get("title") == "scope change" and a["dev-1"]["keys"] == ["T-1"],
          "dev-1 was told to skip them and finish only T-1")
    check("qa-1" in a and a["qa-1"]["keys"] == ["T-4"], "QA started on T-4 at the same time")
    saved_jobs = json.loads(run([PY, "-c", "import sys,json;sys.path.insert(0,'.sdlc/bin');from board import Board;"
                                 "print(json.dumps(Board().meta()['tl']['jobs']))"], repo, env).stdout)
    items = {i["key"]: i for i in json.loads(run(board + ["show", "--json"], repo, env).stdout) if i["type"] == "task"}
    check(items["T-2"]["assignee"] == "dev-2" and items["T-1"]["assignee"] == "dev-1", "board shows the new owners")

    # the watcher wakes the lead when a busy developer moves on while another developer is idle
    run(board + ["show"], repo, env)
    w = subprocess.Popen(team + ["watch", "--every", "5", "--max-minutes", "1"], cwd=repo, env=env,
                         stdout=subprocess.PIPE, text=True, encoding="utf-8")
    import time as _t; _t.sleep(8)
    run([PY, "-c", "import sys,time;sys.path.insert(0,'.sdlc/bin');from board import Board;b=Board();tl=b.meta()['tl'];"
         "tl['jobs']={'dev-1':{'keys':['T-1','T-9'],'kind':'developer','started':time.time(),'budget':0}};b.set_meta(tl=tl)"],
        repo, env)
    _t.sleep(8)  # the watcher sees dev-1 at work first
    (w1 / "app").mkdir(exist_ok=True)
    (w1 / "app" / "z.py").write_text("# more\n", encoding="utf-8")
    run(["git", "add", "-A"], w1, env)
    run(["git", "commit", "-qm", "T-1: part"], w1, env)
    wo = json.loads(w.communicate(timeout=90)[0])
    check(wo.get("work_waiting") == ["dev-1"], f"watcher wakes the lead: dev-1 moved on, dev-2 idle ({wo})")
    run([PY, "-c", "import sys;sys.path.insert(0,'.sdlc/bin');from board import Board;b=Board();tl=b.meta()['tl'];"
         f"tl['jobs']={json.dumps(saved_jobs)};b.set_meta(tl=tl)"], repo, env)

    # finish: dev-1 completes T-1, dev-2 builds T-2/T-3, QA passes everything
    build("dev-1", ["T-1"], d1)
    build("dev-2", ["T-2", "T-3"], Path(a["dev-2"]["file"]).read_text(encoding="utf-8"))
    for _ in range(12):
        done = []
        for x in out["assignments"]:
            if x["agent"].startswith("qa"):
                for k in x["keys"]:
                    run(board + ["--as", x["agent"], "--role", "qa", "qa-pass", k, "ok"], repo, env, ok=False)
                done.append(x["agent"])
        out = step("next", "--done", "dev-1", "dev-2", *done)
        if out["finished"]:
            break
    check(out["finished"], f"run finishes ({out['progress']})")
    files = run(["git", "ls-tree", "-r", "--name-only", "team/2026-01-01-api"], repo, env).stdout
    check(all(f"app/{n}.py" in files for n in "abcd"), "all four tasks merged")
    shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
