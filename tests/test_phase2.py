"""Phase 2: prove the checks. Hidden holdouts and their fence, leaks counted, deliberate bugs, check depth, mission.

The hooks are called exactly as Claude Code calls them (JSON on stdin, exit 2 = blocked). The pipeline runs with
the scripted `claude` stand-in; git, verify, the merge gate and mutate.py are real.
python tests/test_phase2.py
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
HOOKS = KIT / "scripts" / "sdlc_hooks.py"
FAKE = Path(__file__).resolve().parent / "fakes" / "fake_claude.py"
PY = sys.executable
FAILS: list[str] = []


def check(cond: bool, what: str) -> None:
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        FAILS.append(what)


def run(cmd, cwd, env, ok=True, stdin=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
                       input=stdin)
    if ok and r.returncode:
        raise SystemExit(f"failed: {cmd}\n{r.stdout}\n{r.stderr}")
    return r


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="sdlc-p2-"))
    repo = tmp / "repo"
    repo.mkdir()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "SDLC_CLAUDE_CMD": json.dumps([PY, str(FAKE)])}
    for k in ("SDLC_AGENT", "SDLC_ROLE", "CLAUDECODE", "SDLC_HOLDOUT_ACCESS"):
        env.pop(k, None)
    g = lambda *a: run(["git", *a], repo, env).stdout.strip()
    g("init", "-q", "-b", "main")
    g("config", "user.email", "t@x")
    g("config", "user.name", "t")
    # product: a tiny posts module; check.py tests only the limit, not the title rule (a real gap)
    (repo / "posts.py").write_text(
        "def can_publish(title, words):\n"
        "    if not title.strip():\n        return False\n"
        "    return words <= 1000\n", encoding="utf-8")
    (repo / "check.py").write_text(
        "import sys\nfrom posts import can_publish\n"
        "ok = can_publish('Hi', 10) and can_publish('Hi', 1000) and not can_publish('Hi', 1001)\n"
        "sys.exit(0 if ok else 'limit broken')\n", encoding="utf-8")
    run([PY, str(KIT / "scripts" / "init.py"), "--root", str(repo), "--test", f'"{PY}" check.py'], repo, env)
    g("add", "-A")
    g("commit", "-qm", "init")
    check((repo / "sdlc" / "MISSION.md").is_file() and (repo / ".ignore").is_file()
          and "sdlc/holdout/" in (repo / ".ignore").read_text(encoding="utf-8"),
          "init adds MISSION.md, defects.json and .ignore (Grep/Glob skip the holdouts)")

    def hook(mode: str, payload: dict, **extra) -> subprocess.CompletedProcess:
        e = {**env, **extra}
        return run([PY, str(HOOKS), mode], repo, e, ok=False, stdin=json.dumps({"cwd": str(repo), **payload}))

    # 1. the fence
    hold = repo / "sdlc" / "holdout" / "2026-01-01-x.md"
    hold.parent.mkdir(parents=True)
    hold.write_text("## H-1 a deleted post never comes back after a restart\nSteps: delete, restart the server\n",
                    encoding="utf-8")
    g("add", "-A")
    g("commit", "-qm", "holdout")
    rd = {"tool_name": "Read", "tool_input": {"file_path": str(hold)}}
    check(hook("pre-read", rd).returncode == 2, "a builder's Read of a holdout file is refused")
    check(hook("pre-read", rd, SDLC_HOLDOUT_ACCESS="1").returncode == 0, "the holdout agents (access granted) may read it")
    check(hook("pre-read", {**rd, "agent_type": "sdlc:holdout-verifier"}).returncode == 0, "…also as a holdout subagent")
    check(hook("pre-edit", {"tool_name": "Write", "tool_input": {"file_path": str(hold), "content": "x"}}).returncode == 2,
          "a builder can't write there either")
    bash = lambda c, **e: hook("pre-bash", {"tool_name": "Bash", "tool_input": {"command": c}}, **e).returncode
    check(bash("cat sdlc/holdout/2026-01-01-x.md") == 2, "cat of a holdout file is refused")
    check(bash("git show HEAD") == 2, "git show that would print a scenario is refused (git is asked first)")
    check(bash("git log --oneline -3") == 0 and bash("ls") == 0, "ordinary git and shell commands still work")
    hook("post-read", {"tool_name": "Bash", "tool_input": {"command": "grep -r restart ."},
                       "tool_response": {"stdout": "sdlc/holdout/2026-01-01-x.md:## H-1 a deleted post never comes back after a restart"}})
    log = repo / ".git" / "sdlc-holdout-exposures.jsonl"
    check(log.is_file() and len(log.read_text(encoding="utf-8").splitlines()) == 1, "a leak the fence missed is counted")
    for f in ("sdlc/MISSION.md", "sdlc/defects.json"):
        r = hook("pre-edit", {"tool_name": "Edit", "tool_input": {"file_path": str(repo / f), "new_string": "x"}})
        check(r.returncode == 2, f"agents can't edit {f} (humans own it)")
    log.unlink()

    # 2. holdouts in the pipeline: written from intent only (with access), run by the verifier, verdict only
    def new_change(name: str, extra: str = "") -> Path:
        c = repo / "sdlc" / "changes" / f"2026-01-02-{name}"
        c.mkdir(parents=True)
        (c / "intent.md").write_text(f"# {name}\n\nStatus: accepted\n{extra}", encoding="utf-8")
        g("add", "-A")
        g("commit", "-qm", f"intent {name}")
        return c

    def loop(mode: str, **fake) -> None:
        e = {**env, **{f"FAKE_{k.upper()}": v for k, v in fake.items()}}
        run([PY, ".sdlc/bin/loop.py", "--once", "--no-monitor", "--merge-mode", mode], repo, e, ok=False)

    dec = lambda c: json.loads((repo / ".sdlc" / "state" / "merge" / f"{c.name}.json").read_text(encoding="utf-8"))
    c1 = new_change("titles")
    loop("auto", files=json.dumps({"app/notes.py": "x = 1\n"}), holdout="fail")
    d = dec(c1)
    check((repo / "sdlc" / "holdout" / f"{c1.name}.md").is_file() or
          g("ls-tree", "-r", "--name-only", f"sdlc/{c1.name}").count(f"sdlc/holdout/{c1.name}.md") == 1,
          "the holdout writer wrote the scenarios (only because access was granted)")
    check(any("holdout scenarios failed" in x for x in d["reasons"]) and d["result"] == "handed over",
          f"a failed holdout hands the change over ({d['reasons']})")
    check("empty title" not in json.dumps(d["reasons"]), "the decision shows what a user saw, never the scenario text")
    g("checkout", "-q", "main")
    c2 = new_change("titles-ok")
    loop("auto", files=json.dumps({"app/notes2.py": "x = 2\n"}))
    check(dec(c2).get("result") == "merged", f"passing holdouts: merged ({dec(c2).get('reasons')})")

    # 3. a leak on the change's branch makes its holdouts worthless → handed over
    c3 = new_change("leaky")
    g("checkout", "-q", "-b", "sdlc/leaky-x")
    (repo / "notes3.py").write_text("x = 3\n", encoding="utf-8")
    (repo / "sdlc" / "holdout" / f"{c3.name}.md").write_text("## H-1 a post title longer than two hundred characters is cut\n",
                                                             encoding="utf-8")
    (c3 / "assessment.json").write_text(json.dumps({"confident": True, "recommendation": "merge", "reason": "",
                                                     "assumptions": []}), encoding="utf-8")
    g("add", "-A")
    g("commit", "-qm", "leaky change")
    hook("post-read", {"tool_name": "Read", "tool_response": "## H-1 a post title longer than two hundred characters is cut"})
    run([PY, ".sdlc/bin/merge_gate.py", "decide", c3.name, "--mode", "auto", "--branch", "sdlc/leaky-x"], repo, env, ok=False)
    check(any("exposed to a builder" in x for x in dec(c3)["reasons"]), "holdouts seen by a builder: handed over")
    g("checkout", "-q", "main")

    # 4. deliberate bugs: the title rule is untested, so breaking it escapes
    (repo / "sdlc" / "defects.json").write_text(json.dumps({"defects": [
        {"id": "limit-off-by-one", "file": "posts.py", "find": "words <= 1000", "replace": "words < 1000",
         "why": "a 1000-word post would be refused"},
        {"id": "empty-title-allowed", "file": "posts.py", "find": "return False", "replace": "return True",
         "why": "posts without a title could be published"},
        {"id": "stale-anchor", "file": "posts.py", "find": "no such text", "replace": "x"}]}), encoding="utf-8")
    g("add", "-A")
    g("commit", "-qm", "defects")
    r = run([PY, ".sdlc/bin/mutate.py", "--json"], repo, env, ok=False)
    rep = json.loads(r.stdout)
    res = {x["id"]: x["result"] for x in rep["results"]}
    check(res == {"limit-off-by-one": "caught", "empty-title-allowed": "ESCAPED", "stale-anchor": "not injected"},
          f"mutate: caught / ESCAPED / not injected ({res})")
    check(r.returncode == 1 and not g("status", "--porcelain"), "an escape fails the run and the code is restored")
    c4 = new_change("auth-change", "Check: deep\n")
    loop("auto", files=json.dumps({"notes4.txt": "x\n"}))
    d = dec(c4)
    check(d["facts"].get("check_depth") == "deep" and any("Deliberate bugs escaped" in x for x in d["reasons"]),
          f"deep change: escaped bugs hand it over ({d['reasons']})")
    g("checkout", "-q", "main")
    (repo / "check.py").write_text((repo / "check.py").read_text(encoding="utf-8").replace(
        "ok = ", "ok = not can_publish(' ', 5) and "), encoding="utf-8")
    g("commit", "-qam", "test the title rule")
    c5 = new_change("auth-change-2", "Check: deep\n")
    loop("auto", files=json.dumps({"notes5.txt": "x\n"}))
    check(dec(c5).get("result") == "merged", f"once the tests catch every bug: merged ({dec(c5).get('reasons')})")
    c6 = new_change("docs", "")
    loop("auto", files=json.dumps({"docs/guide.md": "# Guide\n"}))
    check(dec(c6)["facts"].get("check_depth") == "light" and not
          (repo / ".sdlc" / "state" / "holdout" / f"{c6.name}.json").exists(), "docs-only change: light, no holdout run")

    # 5. check depth in team mode: QA instructions and time budget follow the task's risk
    tr = tmp / "team"
    tr.mkdir()
    te = {**env, "SDLC_BOARD_DB": str(tr / ".sdlc" / "state" / "board.db")}
    gt = lambda *a: run(["git", *a], tr, te).stdout.strip()
    gt("init", "-q", "-b", "main")
    gt("config", "user.email", "t@x")
    gt("config", "user.name", "t")
    run([PY, str(KIT / "scripts" / "init.py"), "--root", str(tr), "--developers", "2", "--qa-agents", "1"], tr, te)
    ch = tr / "sdlc" / "changes" / "2026-01-01-api"
    ch.mkdir(parents=True)
    (ch / "intent.md").write_text("Status: accepted\n", encoding="utf-8")
    t = lambda i, f, c: {"id": i, "title": f"task {i}", "files": [f], "acceptance": ["ok"], "qa": "check", "ui": False,
                         "depends_on": [], **({"check": c} if c else {})}
    (ch / "breakdown.json").write_text(json.dumps({"epic": {"title": "API"}, "ui": False, "stories": [
        {"id": "S1", "title": "Login", "tasks": [t("T1", "app/auth.py", "")]},
        {"id": "S2", "title": "Docs", "tasks": [t("T2", "app/readme_gen.py", "light")]}]}), encoding="utf-8")
    gt("add", "-A")
    gt("commit", "-qm", "init")
    team, board = [PY, ".sdlc/bin/team.py"], [PY, ".sdlc/bin/board.py"]
    out = json.loads(run(team + ["prepare", "api", "--simulate"], tr, te).stdout)
    for a in out["assignments"]:
        w = Path(re.search(r"YOUR WORKTREE: (.+)", Path(a["file"]).read_text(encoding="utf-8")).group(1).strip())
        k = a["keys"][0]
        (w / "app").mkdir(exist_ok=True)
        (w / "app" / ("auth.py" if k == "T-1" else "readme_gen.py")).write_text("# x\n", encoding="utf-8")
        run(["git", "add", "-A"], w, te)
        run(["git", "commit", "-qm", f"{k}: work"], w, te)
        run(board + ["--as", a["agent"], "--role", "developer", "submit", k, "done"], tr, te)
    out = json.loads(run(team + ["next", "api", "--simulate", "--done", "dev-1", "dev-2"], tr, te).stdout)
    qa = [a for a in out["assignments"] if a["agent"] == "qa-1"]
    text = Path(qa[0]["file"]).read_text(encoding="utf-8") if qa else ""
    first = qa[0]["keys"] if qa else []
    want_deep = "T-1" in first
    check(qa and (("Check depth: DEEP" in text and "about 8 minutes" in text) if want_deep else
                  ("Check depth: LIGHT" in text and "about 5 minutes" in text)),
          f"QA depth follows risk: auth file → deep (8 min), planner 'light' → light (5 min) ({first})")
    shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
