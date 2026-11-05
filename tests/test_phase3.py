"""Phase 3: run for days. Cost on the board, the supervisor, the manager, the timer, phone buttons, parallel work.

Claude Code's session records are written the way Claude Code writes them (a temp CLAUDE_CONFIG_DIR), Telegram
and Slack are a local fake server, everything else is real.
python tests/test_phase3.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

KIT = Path(__file__).resolve().parents[1] / "plugins" / "sdlc"
FAKE = Path(__file__).resolve().parent / "fakes" / "fake_claude.py"
PY = sys.executable
FAILS: list[str] = []
TG: dict = {"sent": [], "updates": []}


def check(cond: bool, what: str) -> None:
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        FAILS.append(what)


def run(cmd, cwd, env, ok=True):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    if ok and r.returncode:
        raise SystemExit(f"failed: {cmd}\n{r.stdout}\n{r.stderr}")
    return r


class Fake(BaseHTTPRequestHandler):  # Telegram Bot API + a Slack incoming webhook
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        out: dict = {"ok": True}
        if self.path.endswith("/sendMessage"):
            TG["sent"].append(body)
        elif self.path.endswith("/getUpdates"):
            out["result"], TG["updates"] = TG["updates"], []
        elif self.path == "/slack":
            TG.setdefault("slack", []).append(body)
        b = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def transcript(base: Path, cwd: Path, agent: str, key: str, steps: list, t0: float) -> None:
    """A teammate's session file as Claude Code writes it: first prompt names the assignment, then tool calls."""
    d = base / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
    d.mkdir(parents=True, exist_ok=True)
    lines = [{"type": "user", "cwd": str(cwd), "timestamp": iso(t0), "message": {"role": "user", "content":
              f"New assignment ({key}): read {cwd}/.sdlc/state/assignments/{agent}-001-{key}.md and do exactly what it says."}}]
    for i, (tool, inp, err, text) in enumerate(steps):
        t = t0 + 5 + i * 5
        lines.append({"type": "assistant", "cwd": str(cwd), "timestamp": iso(t), "message": {
            "id": f"msg_{agent}_{i}", "model": "claude-sonnet-5-5",
            "usage": {"input_tokens": 1000, "output_tokens": 500, "cache_read_input_tokens": 10000,
                      "cache_creation_input_tokens": 0},
            "content": [{"type": "tool_use", "id": f"tu_{agent}_{i}", "name": tool, "input": inp}]}})
        lines.append({"type": "user", "cwd": str(cwd), "timestamp": iso(t + 1), "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"tu_{agent}_{i}", "is_error": err, "content": text}]}})
    (d / f"{agent}.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="sdlc-p3-"))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    fake_url = f"http://127.0.0.1:{srv.server_port}"
    cc = tmp / "claude-config"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "CLAUDE_CONFIG_DIR": str(cc),
           "SDLC_CLAUDE_CMD": json.dumps([PY, str(FAKE)]), "SDLC_TELEGRAM_API": fake_url,
           "SDLC_TELEGRAM_TOKEN": "t0k", "SDLC_SLACK_WEBHOOK": fake_url + "/slack", "SDLC_ENV_FILE": str(tmp / "env")}
    for k in ("SDLC_AGENT", "SDLC_ROLE", "CLAUDECODE", "SDLC_HOLDOUT_ACCESS"):
        env.pop(k, None)

    # ---------------- a team run: cost on the board, and the supervisor
    tr = tmp / "team"
    tr.mkdir()
    te = {**env, "SDLC_BOARD_DB": str(tr / ".sdlc" / "state" / "board.db")}
    g = lambda *a: run(["git", *a], tr, te).stdout.strip()
    g("init", "-q", "-b", "main")
    g("config", "user.email", "t@x")
    g("config", "user.name", "t")
    run([PY, str(KIT / "scripts" / "init.py"), "--root", str(tr), "--developers", "2", "--qa-agents", "1"], tr, te)
    cfgp = tr / ".sdlc" / "config.json"
    cfg = json.loads(cfgp.read_text(encoding="utf-8"))
    cfg["notify"] = {"telegram": {"chat_id": "42"}}
    cfgp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    ch = tr / "sdlc" / "changes" / "2026-01-01-api"
    ch.mkdir(parents=True)
    (ch / "intent.md").write_text("Status: accepted\n", encoding="utf-8")
    t = lambda i, f: {"id": i, "title": f"task {i}", "files": [f], "acceptance": ["ok"], "qa": "check", "ui": False,
                      "depends_on": []}
    (ch / "breakdown.json").write_text(json.dumps({"epic": {"title": "API"}, "ui": False, "stories": [
        {"id": "S1", "title": "A", "tasks": [t("T1", "app/a.py")]}, {"id": "S2", "title": "B", "tasks": [t("T2", "app/b.py")]}]}),
        encoding="utf-8")
    g("add", "-A")
    g("commit", "-qm", "init")
    team = [PY, ".sdlc/bin/team.py"]
    out = json.loads(run(team + ["prepare", "api", "--simulate"], tr, te).stdout)
    wts = {a["agent"]: Path(re.search(r"YOUR WORKTREE: (.+)", Path(a["file"]).read_text(encoding="utf-8")).group(1).strip())
           for a in out["assignments"]}
    now = time.time()
    fail = ("Bash", {"command": "npm test"}, True, "Exit code 1\nError: Cannot find module 'app/b'")
    transcript(cc, wts["dev-1"], "dev-1", "T-1", [fail, fail, fail], now)
    rd = ("Read", {"file_path": str(wts["dev-2"] / "app" / "spec.py")}, False, "content")
    transcript(cc, wts["dev-2"], "dev-2", "T-2", [rd, rd, rd, rd], now)

    port = socket.socket()
    port.bind(("127.0.0.1", 0))
    bport = port.getsockname()[1]
    port.close()
    bs = subprocess.Popen([PY, ".sdlc/bin/board_server.py", "--port", str(bport)], cwd=tr, env=te,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        snap = {}
        for _ in range(30):
            try:
                snap = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{bport}/api/board?since=0", timeout=5).read())
                break
            except Exception:
                time.sleep(0.5)
        c = snap.get("cost") or {}
        # each call: 1000 in × $2 + 500 out × $10 + 10000 cache read × $0.10 per million = $0.008
        check(abs(c.get("total", 0) - 7 * 0.008) < 1e-6, f"board: total cost of the run ({c.get('total')})")
        check(abs(c.get("tasks", {}).get("T-1", 0) - 0.024) < 1e-6 and abs(c.get("tasks", {}).get("T-2", 0) - 0.032) < 1e-6,
              f"board: cost per card, from who worked on what ({c.get('tasks')})")
        check(abs(c.get("agents", {}).get("dev-2", 0) - 0.032) < 1e-6, "board: cost per teammate")
    finally:
        bs.kill()

    r = json.loads(run([PY, ".sdlc/bin/supervisor.py", "--json"], tr, te).stdout)
    kinds = {f["agent"]: f["kind"] for f in r}
    check(kinds.get("dev-1") == "looping" and kinds.get("dev-2") == "rereading",
          f"supervisor: dev-1 looping on a failing command, dev-2 re-reading a file ({kinds})")
    evs = json.loads(run([PY, ".sdlc/bin/board.py", "show", "--json"], tr, te).stdout)  # board still fine
    hist = run([PY, ".sdlc/bin/board.py", "task", "T-1"], tr, te).stdout
    check("would tell dev-1" in hist and "npm test" in hist, "supervisor (trial): only notes on the board what it would say")
    r2 = json.loads(run([PY, ".sdlc/bin/supervisor.py", "--json"], tr, te).stdout)
    check(r2 == [], "supervisor: each finding reported once per assignment")
    cfg["team"]["supervisor"] = {"mode": "act"}
    cfgp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    transcript(cc, wts["dev-1"], "qa-1", "T-1", [], now - 3 * 3600)  # unrelated
    b = [PY, ".sdlc/bin/board.py"]
    run(b + ["--as", "dev-1", "--role", "developer", "submit", "T-1", "done"], tr, te)
    run([PY, "-c", "import sys;sys.path.insert(0,'.sdlc/bin');from board import Board;b=Board();tl=b.meta()['tl'];"
         "tl['jobs']['dev-1']['started']-=120;b.set_meta(tl=tl)"], tr, te)
    w = json.loads(run(team + ["watch", "--every", "5", "--max-minutes", "1"], tr, te).stdout)
    sup = w.get("supervisor") or []
    check(any(f["kind"] == "silent_done" and f["to"] == "lead" and "--done dev-1" in f.get("do", "") for f in sup),
          f"supervisor (act): dev-1 handed in but never told the lead → watch wakes the lead to run next ({sup})")

    # ---------------- phone notifications with buttons (Telegram) + Slack alerts
    TG["sent"].clear()
    # an escalated task reaches the phone with an Answer button; the reply resumes it
    run([PY, "-c", "import sys;sys.path.insert(0,'.sdlc/bin');from board import Board;b=Board();"
         "b.update('T-2','lead',note='ESCALATED to a human: which date format?',status='blocked');"
         "b.set_meta(escalated=['T-2'])"], tr, te)
    run(team + ["next", "api", "--simulate"], tr, te)
    msg = next((m for m in TG["sent"] if "T-2 needs you" in m.get("text", "")), None)
    btn = (msg or {}).get("reply_markup", {}).get("inline_keyboard", [[{}]])[0][0]
    check(msg and "which date format" in msg["text"] and btn.get("callback_data") == "answer:T-2",
          "phone: an escalation arrives on Telegram with an Answer button")
    TG["updates"] = [{"update_id": 1, "callback_query": {"id": "q1", "data": "answer:T-2", "from": {"username": "kunal"},
                                                         "message": {"chat": {"id": 42}}}}]
    run([PY, ".sdlc/bin/notify.py", "serve", "--once"], tr, te)
    TG["updates"] = [{"update_id": 2, "message": {"chat": {"id": 42}, "from": {"username": "kunal"}, "text": "Use ISO 8601"}}]
    run([PY, ".sdlc/bin/notify.py", "serve", "--once"], tr, te)
    esc = json.loads(run([PY, "-c", "import sys,json;sys.path.insert(0,'.sdlc/bin');from board import Board;"
                          "print(json.dumps(Board().meta().get('escalated',[])))"], tr, te).stdout)
    check(esc == [] and "Use ISO 8601" in run(b + ["task", "T-2"], tr, te).stdout,
          "phone: Answer → your reply resumed the task with it as guidance")
    TG["updates"] = [{"update_id": 3, "callback_query": {"id": "q2", "data": "release:REL-1", "from": {"username": "x"},
                                                         "message": {"chat": {"id": 999}}}}]
    run([PY, ".sdlc/bin/notify.py", "serve", "--once"], tr, te)
    check(not (tr / ".sdlc" / "state" / "release-approval.json").exists(), "phone: a press from another chat is ignored")

    # ---------------- out of the loop: parallel changes, merge notifications, manager, timer
    rp = tmp / "repo"
    rp.mkdir()
    gr = lambda *a: run(["git", *a], rp, env).stdout.strip()
    gr("init", "-q", "-b", "main")
    gr("config", "user.email", "t@x")
    gr("config", "user.name", "t")
    (rp / "check.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    run([PY, str(KIT / "scripts" / "init.py"), "--root", str(rp), "--test", f'"{PY}" check.py'], rp, env)
    rc = json.loads((rp / ".sdlc" / "config.json").read_text(encoding="utf-8"))
    rc["notify"] = {"telegram": {"chat_id": "42"}}
    (rp / ".sdlc" / "config.json").write_text(json.dumps(rc, indent=2), encoding="utf-8")
    for n in ("one", "two"):
        c = rp / "sdlc" / "changes" / f"2026-01-01-{n}"
        c.mkdir(parents=True)
        (c / "intent.md").write_text("Status: accepted\n", encoding="utf-8")
    gr("add", "-A")
    gr("commit", "-qm", "init")
    TG["sent"].clear()
    e = {**env, "FAKE_FILES": json.dumps({"app/x_{}.py".format(os.getpid()): "x = 1\n"})}
    r = run([PY, ".sdlc/bin/loop.py", "--once", "--no-monitor", "--merge-mode", "auto", "--parallel", "2"], rp,
            {**e, "FAKE_FILES": "{}"}, ok=False)
    st = json.loads((rp / ".sdlc" / "state" / "loop.json").read_text(encoding="utf-8"))
    merges = [ln for ln in gr("log", "--format=%s", "main").splitlines() if "merge (auto" in ln]
    check(len(merges) == 2 and all(v["result"] == "merged" for v in st.values()),
          f"parallel: two changes at once, each in its own worktree, both merged one at a time ({st})")
    check(not list((rp / ".sdlc" / "worktrees").glob("loop-*")) and not list((rp / ".sdlc" / "state" / "claims").glob("*")),
          "parallel: worktrees and claims cleaned up")
    check(any("merged" in m.get("text", "") for m in TG["sent"]), "phone: each merge is announced")
    # a handed-over change: the phone's Merge anyway button merges it, hard limits still checked
    c3 = rp / "sdlc" / "changes" / "2026-01-01-three"
    c3.mkdir(parents=True)
    (c3 / "intent.md").write_text("Status: accepted\n", encoding="utf-8")
    gr("add", "-A")
    gr("commit", "-qm", "intent three")
    run([PY, ".sdlc/bin/loop.py", "--once", "--no-monitor", "--merge-mode", "auto"], rp,
        {**env, "FAKE_CONFIDENT": "0", "FAKE_FILES": json.dumps({"app/three.py": "x = 3\n"})}, ok=False)
    gr("checkout", "-q", "main")
    ho = next((m for m in TG["sent"] if "three needs your review" in m.get("text", "")), None)
    check(ho and ho["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "merge:2026-01-01-three",
          "phone: a handed-over merge arrives with a Merge anyway button")
    TG["updates"] = [{"update_id": 9, "callback_query": {"id": "q9", "data": "merge:2026-01-01-three",
                                                         "from": {"username": "kunal"}, "message": {"chat": {"id": 42}}}}]
    run([PY, ".sdlc/bin/notify.py", "serve", "--once"], rp, env)
    gr("checkout", "-q", "main")
    d3 = json.loads((rp / ".sdlc" / "state" / "merge" / f"{c3.name}.json").read_text(encoding="utf-8"))
    check(d3.get("result") == "merged" and d3["facts"].get("approved_by") == "telegram:kunal",
          "phone: Merge anyway merged it (your approval overrules the agent's doubt, not the facts)")

    # manager: a crashed run is retried once; a stale lock is cleaned
    st = json.loads((rp / ".sdlc" / "state" / "loop.json").read_text(encoding="utf-8"))
    st["2026-01-01-ghost"] = {"result": "failed (exit 1)", "at": "2026-01-01T00:00:00Z"}
    (rp / ".sdlc" / "state" / "loop.json").write_text(json.dumps(st), encoding="utf-8")
    lock = rp / ".git" / "index.lock"
    lock.write_text("")
    os.utime(lock, (1, 1))
    rep = json.loads(run([PY, ".sdlc/bin/manager.py", "--fix", "--json"], rp, env).stdout)
    whats = {x["what"] for x in rep["findings"]}
    st = json.loads((rp / ".sdlc" / "state" / "loop.json").read_text(encoding="utf-8"))
    check("retrying a failed run" in whats and "2026-01-01-ghost" not in st and not lock.exists(),
          f"manager: retries a crashed run once and cleans a stale lock ({whats})")
    st["2026-01-01-ghost"] = {"result": "failed (exit 1)", "at": "2026-01-01T00:00:00Z"}
    (rp / ".sdlc" / "state" / "loop.json").write_text(json.dumps(st), encoding="utf-8")
    TG["sent"].clear()
    rep = json.loads(run([PY, ".sdlc/bin/manager.py", "--fix", "--json"], rp, env).stdout)
    check(any(x["what"] == "failed run" for x in rep["findings"]) and any("Factory check" in m["text"] for m in TG["sent"]),
          "manager: a second crash is reported to the phone instead of retried forever")

    # timer: the files it would register, a tick, halt
    r = run([PY, ".sdlc/bin/schedule.py", "install", "--every", "7"], rp, env)
    files = list((rp / ".sdlc" / "state" / "schedule").glob("*"))
    body = "".join(f.read_text(encoding="utf-8") for f in files)
    check(files and "schedule.py" in body and " fire" in body and ("7min" in body or "420" in body or "/MO 7" in body),
          f"timer: unit files written for this OS ({[f.name for f in files]})")
    run([PY, ".sdlc/bin/schedule.py", "halt"], rp, env)
    run([PY, ".sdlc/bin/schedule.py", "fire"], rp, env)
    log = (rp / ".sdlc" / "state" / "schedule.log").read_text(encoding="utf-8")
    check("halted" in log, "timer: a halted factory starts nothing")
    run([PY, ".sdlc/bin/schedule.py", "unhalt"], rp, env)
    run([PY, ".sdlc/bin/schedule.py", "fire"], rp, env)
    log = (rp / ".sdlc" / "state" / "schedule.log").read_text(encoding="utf-8")
    hb = json.loads((rp / ".sdlc" / "state" / "loop-heartbeat.json").read_text(encoding="utf-8"))
    check("tick: loop.py --once" in log and "manager: due" in log and hb.get("at"),
          "timer: a tick runs the loop once and the manager when it is due")

    srv.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
