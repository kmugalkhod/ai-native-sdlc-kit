"""End-to-end test of the agent-teams lead helper (team.py prepare / next / wrap) with scripted teammates.

It plays every teammate the way a real Claude teammate would — through the board CLI with --as — and checks:
story batching, the design gate, a QA failure that goes back to the same developer, a blocked task answered by a
teammate, a session restart in the middle of the run, merging per story, and the final integration report.
Runs on Linux, macOS and Windows:  python tests/test_teamlead.py
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


def run(cmd, cwd, env=None, ok=True):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    if ok and r.returncode:
        raise SystemExit(f"command failed: {cmd}\n{r.stdout}\n{r.stderr}")
    return r


BREAKDOWN = {
    "epic": {"title": "Bookmarks", "description": "save and find links"}, "ui": True,
    "stories": [
        {"id": "S1", "title": "Foundation", "tasks": [
            {"id": "T1", "title": "Backend skeleton", "files": ["app/main.py"], "ui": False, "qa": "none",
             "acceptance": ["app starts"], "depends_on": []}]},
        {"id": "S2", "title": "Save bookmarks", "tasks": [
            {"id": "T2", "title": "POST /bookmarks", "files": ["app/api.py"], "ui": False, "qa": "curl it",
             "acceptance": ["201 on valid input"], "depends_on": ["T1"]},
            {"id": "T3", "title": "Storage", "files": ["app/db.py"], "ui": False, "qa": "restart keeps data",
             "acceptance": ["survives restart"], "depends_on": ["T1"]}]},
        {"id": "S3", "title": "Find bookmarks", "tasks": [
            {"id": "T4", "title": "GET /bookmarks?q=", "files": ["app/search.py"], "ui": False, "qa": "curl it",
             "acceptance": ["filters by q"], "depends_on": ["T1"]}]},
        {"id": "S4", "title": "Web page", "tasks": [
            {"id": "T5", "title": "Bookmarks page", "files": ["web/index.html"], "ui": True, "qa": "browser",
             "acceptance": ["lists bookmarks"], "depends_on": ["T2"]}]},
    ]}


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="sdlc-tl-"))
    repo = tmp / "repo"
    repo.mkdir()
    env = {**os.environ, "SDLC_BOARD_DB": str(repo / ".sdlc" / "state" / "board.db"), "PYTHONIOENCODING": "utf-8"}
    env.pop("SDLC_AGENT", None)
    env.pop("SDLC_ROLE", None)
    run(["git", "init", "-q", "-b", "main"], repo)
    run(["git", "config", "user.email", "t@x"], repo)
    run(["git", "config", "user.name", "t"], repo)
    run([PY, str(KIT / "scripts" / "init.py"), "--root", str(repo), "--developers", "2", "--qa-agents", "1",
         "--setup", f'"{PY}" -c "print(1)"'], repo, env)
    ch = repo / "sdlc" / "changes" / "2026-01-01-bookmarks"
    ch.mkdir(parents=True)
    (ch / "intent.md").write_text("# Intent\n\nStatus: accepted\n", encoding="utf-8")
    (ch / "breakdown.json").write_text(json.dumps(BREAKDOWN, indent=2), encoding="utf-8")
    (repo / "README.md").write_text("bookmarks\n", encoding="utf-8")
    (repo / "requirements.txt").write_text("", encoding="utf-8")  # a manifest, so merges trigger installs
    run(["git", "add", "-A"], repo, env)
    run(["git", "commit", "-qm", "init"], repo, env)
    team = [PY, ".sdlc/bin/team.py"]
    board = [PY, ".sdlc/bin/board.py"]

    def step(cmd, done=()):
        r = run(team + [cmd, "bookmarks", "--simulate"] + (["--done", *done] if done else []), repo, env)
        return json.loads(r.stdout)

    def b(agent, role, *args):
        return run(board + ["--as", agent, "--role", role, *args], repo, env, ok=False)

    seen = {"spawn": set(), "batches": [], "qa_fail_sent": False, "blocked_once": False, "restarted": False,
            "design_approved": False}

    def act(a) -> str:
        text = Path(a["file"]).read_text(encoding="utf-8")
        wt = Path(re.search(r"YOUR WORKTREE: (.+)", text).group(1).strip())
        agent, keys = a["agent"], a["keys"]
        if a["action"] == "spawn":
            seen["spawn"].add(agent)
        if a["agent_type"] == "sdlc:designer":
            (wt / "DESIGN.md").write_text("# Design\n", encoding="utf-8")
            d = wt / ch.relative_to(repo) / "design"
            d.mkdir(parents=True, exist_ok=True)
            (d / "mockup.html").write_text("<!doctype html><title>m</title>", encoding="utf-8")
            run(["git", "add", "-A"], wt, env)
            run(["git", "commit", "-qm", "D-1: design"], wt, env)
            b(agent, "designer", "design-ready", keys[0], "dark + lime")
        elif "QA for story" in text:
            seen.setdefault("qa_runs", []).append(keys)
            for k in keys:
                if k == "T-2" and not seen["qa_fail_sent"]:
                    seen["qa_fail_sent"] = True
                    b(agent, "qa", "qa-fail", k, "empty url accepted · expected 400 · got 201")
                else:
                    ev = wt / ".sdlc" / "evidence" / f"{k}-api.txt"
                    ev.parent.mkdir(parents=True, exist_ok=True)
                    if not seen.get("no_proof_tried"):  # a PASS without proof, and with stale proof, is refused
                        seen["no_proof_tried"] = True
                        r1 = b(agent, "qa", "qa-pass", k, "checked")
                        ev.write_text("old", encoding="utf-8")
                        os.utime(ev, (1, 1))
                        r2 = b(agent, "qa", "qa-pass", k, "checked", "--evidence", str(ev))
                        check(r1.returncode != 0 and "proof" in (r1.stdout + r1.stderr), "PASS without evidence refused")
                        check(r2.returncode != 0 and "before this QA check started" in (r2.stdout + r2.stderr),
                              "PASS with stale evidence refused")
                    ev.write_text(f"HTTP/1.1 201 Created\n{k} ok\n", encoding="utf-8")
                    r = b(agent, "qa", "qa-pass", k, "checked", "--evidence", str(ev))
                    check(r.returncode == 0, f"PASS with fresh evidence accepted ({k})") if k == "T-3" else None
        elif "is BLOCKED on task" in text:
            seen["helped"] = True
            dev = re.search(r"Your teammate (\S+) is BLOCKED", text).group(1)
            b(agent, "developer", "ask", dev, "use sqlite, file data.db", "--task", keys[0])
        else:  # developer batch
            seen["batches"].append(keys)
            st = seen.get("snapshot", {})  # the board as it was when this assignment was handed out
            if any(st.get(d, {}).get("status") == "in_qa" for k in keys for d in st.get(k, {}).get("depends_on", [])):
                seen["optimistic"] = True
            for k in keys:
                if k == "T-4" and not seen["blocked_once"]:
                    seen["blocked_once"] = True
                    b(agent, "developer", "blocked", k, "which search syntax?")
                    return agent
                f = wt / "src" / f"{k.lower()}.py"
                f.parent.mkdir(exist_ok=True)
                f.write_text(f"# {k} by {agent} ({len(text)})\n", encoding="utf-8")
                run(["git", "add", "-A"], wt, env)
                run(["git", "commit", "-qm", f"{k}: work"], wt, env)
            for k in keys:
                b(agent, "developer", "submit", k, "done, tests green")
        return agent

    out = step("prepare")
    check(bool(out["assignments"]), "prepare hands out first assignments")
    first = {a["agent"]: a["keys"] for a in out["assignments"]}
    check("designer" in first, "designer starts at once on the design")
    check(any("T-1" in k for k in first.values()), "a developer starts the skeleton at once (not blocked by design)")
    for _ in range(40):
        if not out["assignments"] and not out["working"] and not out["finished"] and not out["waiting_for_human"]:
            check(False, f"lead stalled: nothing assigned, nothing running ({out['progress']})")
            break
        seen["snapshot"] = {i["key"]: i for i in json.loads(run(board + ["show", "--json"], repo, env).stdout)}
        done = [act(a) for a in out["assignments"]]
        for h in out["waiting_for_human"]:
            if h["what"] == "design approval":
                run(board + ["design-approve", h["key"], "looks good"], repo, env)
                seen["design_approved"] = True
        if not seen["restarted"] and seen["qa_fail_sent"]:  # the session crashes once, mid-run (power cut)
            seen["restarted"] = True
            locks = [repo / ".git" / "index.lock"] + [w / "index.lock" for w in (repo / ".git" / "worktrees").iterdir()]
            for lk in locks:
                lk.write_text("", encoding="utf-8")
                os.utime(lk, (1, 1))  # left behind long ago
            out = step("prepare")
            check(not any(lk.exists() for lk in locks), "stale git locks from the crash removed on restart")
        else:
            out = step("next", done)
        if out["finished"]:
            break
    check(out["finished"], f"run finishes ({out['progress']})")
    items = json.loads(run(board + ["show", "--json"], repo, env).stdout)
    tasks = {i["key"]: i for i in items if i["type"] == "task"}
    check(all(t["status"] == "done" for t in tasks.values()), "every task is done")
    check(tasks["T-2"]["qa_rounds"] == 1, "QA failure on T-2 went back and was fixed")
    check(tasks["T-2"]["assignee"] == tasks["T-3"]["assignee"], "T-2 and T-3 (same story) built by one developer")
    check(any(set(k) == {"T-2", "T-3"} for k in seen["batches"]), "story S-2 assigned as one batch")
    check(seen["design_approved"], "design gate asked the human")
    check(seen["restarted"], "session restart mid-run recovered")
    check(seen["spawn"] >= {"dev-1", "dev-2", "qa-1", "designer"}, "each teammate spawned")
    log = run(["git", "log", "--oneline", "team/2026-01-01-bookmarks"], repo, env).stdout
    files = run(["git", "ls-tree", "-r", "--name-only", "team/2026-01-01-bookmarks"], repo, env).stdout
    check(all(f"src/t-{i}.py" in files for i in range(1, 6)), "all task code merged into the team branch")
    check("DESIGN.md" in files, "design merged into the team branch")
    check(seen.get("optimistic", False), "a developer started on top of work still in QA (no idle wait)")
    check(seen.get("helped", False), "blocked T-4 got a teammate's help and then finished")
    check(tasks["T-1"]["qa_by"] == "pass:lead", "setup task T-1 verified by the lead, no QA agent run")
    evs = [e for e in json.loads(run(board + ["show", "--json"], repo, env).stdout)]  # board still readable
    kept = list((repo / ".sdlc" / "state" / "evidence").glob("T-*/*"))
    check(len(kept) >= 3, f"evidence copied next to the board ({len(kept)} files)")
    st = run(["git", "status", "--porcelain"], repo, env).stdout + run(
        ["git", "ls-tree", "-r", "--name-only", "team/2026-01-01-bookmarks"], repo, env).stdout
    check(".sdlc/evidence" not in st, "evidence files are never committed")
    check(not any("T-1" in k for k in seen.get("qa_runs", [])), "QA never spent a run on the setup task")
    check(any(set(k) >= {"T-2", "T-3"} or set(k) == {"T-3"} for k in seen.get("qa_runs", [])),
          "QA tests story S-2 as a group")
    check(len(seen["batches"]) < len(tasks) + 3, f"few developer assignments ({len(seen['batches'])} for {len(tasks)} tasks)")
    print("   developer assignments:", seen["batches"])
    print("   QA assignments:", seen.get("qa_runs"))
    w = run(team + ["wrap", "bookmarks", "--simulate"], repo, env, ok=False)
    check(w.returncode == 0, "wrap writes the report and exits 0")
    check("main" in run(["git", "branch", "--show-current"], repo, env).stdout, "main is untouched (still on main)")
    # time check: a teammate past its budget is reported once, with a message that never tells it to stop
    import time as _t
    run([PY, "-c", "import sys,time;sys.path.insert(0,'.sdlc/bin');from board import Board;b=Board();"
         "b.set_meta(tl={**(b.meta().get('tl') or {}),'jobs':{'qa-1':{'keys':['T-9'],'kind':'qa',"
         "'started':time.time()-600,'budget':4},'dev-1':{'keys':['T-8'],'kind':'dev','started':time.time(),'budget':24}}})"],
        repo, env)
    w1 = json.loads(run(team + ["watch", "--every", "5", "--max-minutes", "1"], repo, env).stdout)["over_budget"]
    check([x["agent"] for x in w1] == ["qa-1"] and "not a stop" in w1[0]["message"], "watch reports the late teammate only")
    t0 = _t.time()
    w2 = json.loads(run(team + ["watch", "--every", "5", "--max-minutes", "1"], repo, env).stdout)["over_budget"]
    check(w2 == [] and _t.time() - t0 > 50, "the same assignment is not reported twice")
    shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
