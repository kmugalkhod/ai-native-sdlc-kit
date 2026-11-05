"""QA never sits idle while a developer is still on the rest of its story: tasks already handed in get tested at once,
the watcher wakes the lead for them, and the branch still merges only after every task on it has passed.
python tests/test_early_qa.py
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


def proof(repo: Path, key: str) -> str:
    """What a QA agent saves during its check (a curl response, a test log)."""
    f = repo / ".sdlc" / "evidence" / f"{key}-api.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(f"HTTP/1.1 200 OK\n{key} checked\n", encoding="utf-8")
    return str(f)


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
    tmp = Path(tempfile.mkdtemp(prefix="sdlc-eq-"))
    repo = tmp / "repo"
    repo.mkdir()
    env = {**os.environ, "SDLC_BOARD_DB": str(repo / ".sdlc" / "state" / "board.db"), "PYTHONIOENCODING": "utf-8"}
    env.pop("SDLC_AGENT", None)
    run(["git", "init", "-q", "-b", "main"], repo, env)
    run(["git", "config", "user.email", "t@x"], repo, env)
    run(["git", "config", "user.name", "t"], repo, env)
    run([PY, str(KIT / "scripts" / "init.py"), "--root", str(repo), "--developers", "1", "--qa-agents", "1"], repo, env)
    ch = repo / "sdlc" / "changes" / "2026-01-01-api"
    ch.mkdir(parents=True)
    (ch / "intent.md").write_text("Status: accepted\n", encoding="utf-8")
    t = lambda i, f, d: {"id": i, "title": f"task {i}", "files": [f], "acceptance": ["ok"], "qa": "check", "ui": False,
                         "depends_on": d}
    (ch / "breakdown.json").write_text(json.dumps({"epic": {"title": "API"}, "ui": False, "stories": [
        {"id": "S1", "title": "Providers", "tasks": [t("T1", "app/a.py", []), t("T2", "app/b.py", ["T1"])]}]}),
        encoding="utf-8")
    run(["git", "add", "-A"], repo, env)
    run(["git", "commit", "-qm", "init"], repo, env)
    team, board = [PY, ".sdlc/bin/team.py"], [PY, ".sdlc/bin/board.py"]
    step = lambda cmd, *a: json.loads(run(team + [cmd, "api", "--simulate", *a], repo, env).stdout)
    status = lambda: {i["key"]: i["status"] for i in json.loads(run(board + ["show", "--json"], repo, env).stdout)
                      if i["type"] == "task"}

    def build(keys, text):
        w = Path(re.search(r"YOUR WORKTREE: (.+)", text).group(1).strip())
        for k in keys:
            (w / "app").mkdir(exist_ok=True)
            (w / "app" / {"T-1": "a.py", "T-2": "b.py"}[k]).write_text(f"# {k}\n", encoding="utf-8")
            run(["git", "add", "-A"], w, env)
            run(["git", "commit", "-qm", f"{k}: work"], w, env)
            run(board + ["--as", "dev-1", "--role", "developer", "submit", k, "done"], repo, env)

    out = step("prepare")
    a = {x["agent"]: x for x in out["assignments"]}
    check(a.get("dev-1", {}).get("keys") == ["T-1", "T-2"], "dev-1 got the story")
    d1 = Path(a["dev-1"]["file"]).read_text(encoding="utf-8")
    build(["T-1"], d1)  # hands in T-1, still building T-2
    w = json.loads(run(team + ["watch", "--every", "5", "--max-minutes", "1"], repo, env).stdout)
    check(w.get("work_waiting") == ["T-1"], f"watcher wakes the lead for handed-in T-1 ({w})")
    out = step("next")
    a = {x["agent"]: x for x in out["assignments"]}
    check(a.get("qa-1", {}).get("keys") == ["T-1"], "QA starts on T-1 while dev-1 is still on T-2")
    run(board + ["--as", "qa-1", "--role", "qa", "qa-pass", "T-1", "ok", "--evidence", proof(repo, "T-1")], repo, env)
    out = step("next", "--done", "qa-1")
    check(status()["T-1"] == "in_qa", "T-1 passed but waits: the branch merges only when T-2 has passed too")
    build(["T-2"], d1)
    out = step("next", "--done", "dev-1")
    a = {x["agent"]: x for x in out["assignments"]}
    check(a.get("qa-1", {}).get("keys") == ["T-2"], "QA then tests only T-2")
    run(board + ["--as", "qa-1", "--role", "qa", "qa-pass", "T-2", "ok", "--evidence", proof(repo, "T-2")], repo, env)
    run([PY, "-c", "import sys;sys.path.insert(0,'.sdlc/bin');from board import Board;b=Board();tl=b.meta()['tl'];"
         "tl['jobs']={};b.set_meta(tl=tl)"], repo, env)  # QA passed it but never messaged the lead
    w = json.loads(run(team + ["watch", "--every", "5", "--max-minutes", "1"], repo, env).stdout)
    check("merge T-1" in w.get("work_waiting", []), f"watcher wakes the lead when a story is ready to merge ({w})")
    out = step("next")
    check(out["finished"] and set(status().values()) == {"done"}, f"both merged, run finished ({out['progress']})")
    shutil.rmtree(tmp, ignore_errors=True)
    replan_mid_run()
    print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED")
    sys.exit(1 if FAILS else 0)


def replan_mid_run() -> None:
    """Editing breakdown.json during a run: tasks still in To Do take the new dependencies; started ones don't move."""
    tmp = Path(tempfile.mkdtemp(prefix="sdlc-rp-"))
    repo = tmp / "repo"
    repo.mkdir()
    env = {**os.environ, "SDLC_BOARD_DB": str(repo / ".sdlc" / "state" / "board.db"), "PYTHONIOENCODING": "utf-8"}
    env.pop("SDLC_AGENT", None)
    run(["git", "init", "-q", "-b", "main"], repo, env)
    run(["git", "config", "user.email", "t@x"], repo, env)
    run(["git", "config", "user.name", "t"], repo, env)
    run([PY, str(KIT / "scripts" / "init.py"), "--root", str(repo), "--developers", "1", "--qa-agents", "1"], repo, env)
    ch = repo / "sdlc" / "changes" / "2026-01-01-api"
    ch.mkdir(parents=True)
    (ch / "intent.md").write_text("Status: accepted\n", encoding="utf-8")
    t = lambda i, d: {"id": i, "title": f"task {i}", "files": [f"app/{i}.py"], "acceptance": ["ok"], "qa": "check",
                      "ui": False, "depends_on": d}
    bd = {"epic": {"title": "API"}, "ui": False, "stories": [
        {"id": "S1", "title": "A", "tasks": [t("T1", [])]}, {"id": "S2", "title": "B", "tasks": [t("T2", ["T1"])]},
        {"id": "S3", "title": "C", "tasks": [t("T3", ["T2"])]}]}
    (ch / "breakdown.json").write_text(json.dumps(bd), encoding="utf-8")
    run(["git", "add", "-A"], repo, env)
    run(["git", "commit", "-qm", "init"], repo, env)
    team, board = [PY, ".sdlc/bin/team.py"], [PY, ".sdlc/bin/board.py"]
    run(team + ["prepare", "api", "--simulate"], repo, env)  # dev-1 starts T-1; T-2, T-3 wait
    bd["stories"][2]["tasks"][0]["depends_on"] = ["T1"]
    bd["stories"][0]["tasks"][0]["title"] = "renamed while being built"
    (ch / "breakdown.json").write_text(json.dumps(bd), encoding="utf-8")
    r = run(team + ["plan", "api", "--simulate"], repo, env)
    items = {i["key"]: i for i in json.loads(run(board + ["show", "--json"], repo, env).stdout) if i["type"] == "task"}
    check(items["T-3"]["depends_on"] == ["T-1"], f"a To Do task took the new dependency ({items['T-3']['depends_on']})")
    check(items["T-1"]["title"] == "task T1", "a started task was left as it is")
    bd["stories"][2]["tasks"].append(t("T4", []))
    (ch / "breakdown.json").write_text(json.dumps(bd), encoding="utf-8")
    r = run(team + ["plan", "api", "--simulate"], repo, env, ok=False)
    check("can't be added or removed" in (r.stdout + r.stderr), "adding a task mid-run is refused with a clear reason")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
