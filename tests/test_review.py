"""Review room: the board server lists what the agents wrote, shows versions, lets the human chat with the agent that
wrote a document (resuming its session), and approve / request changes / resume from there.
python tests/test_review.py
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
FAKE = json.dumps([sys.executable, str(KIT / "tests" / "fakes" / "fake_review_claude.py")])
fails = 0

ARCH = """# Architecture

Status: proposed
Change: sdlc/changes/{change}
Updated: today

## Components

- Ingestion API
- Worker

```mermaid
flowchart LR
  api[Ingestion API] --> q[/Queue/] --> w[Worker] --> db[(Postgres)]
```
"""


def check(name, ok, detail=""):
    global fails
    fails += not ok
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail and not ok else ""))


def sh(root, *c):
    return subprocess.run(list(c), cwd=root, capture_output=True, text=True)


def setup():
    root = Path(tempfile.mkdtemp(prefix="sdlc-rv-"))
    for c in (["git", "init", "-q", "-b", "main"], ["git", "config", "user.email", "t@x"], ["git", "config", "user.name", "Kunal"]):
        sh(root, *c)
    sh(root, sys.executable, str(KIT / "plugins/sdlc/scripts/init.py"), "--root", str(root))
    sh(root, sys.executable, str(root / ".sdlc/bin/sdlc.py"), "new", "trace-app")
    ch = next((root / "sdlc" / "changes").glob("*trace-app*"))
    (ch / "intent.md").write_text("# Intent\n\nStatus: accepted\n\nBuild a trace app.\n", encoding="utf-8")
    (ch / "spec.md").write_text("# Spec\n\nStatus: accepted\n", encoding="utf-8")
    (root / "sdlc" / "ARCHITECTURE.md").write_text(ARCH.format(change=ch.name), encoding="utf-8")
    (root / "sdlc" / "adr").mkdir(exist_ok=True)
    (root / "sdlc" / "adr" / "0001-postgres-first.md").write_text("# ADR 0001 Postgres first\n\nStatus: proposed\n", encoding="utf-8")
    (root / "sdlc" / "architecture.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
    (root / "secret.png").write_bytes(b"x")
    sh(root, "git", "add", "-A")
    sh(root, "git", "commit", "-qm", "architecture proposed")
    return root, ch


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Srv:
    def __init__(self, root):
        self.port = free_port()
        self.p = subprocess.Popen([sys.executable, str(root / ".sdlc/bin/board_server.py"), "--port", str(self.port)], cwd=root,
                                  env={**os.environ, "SDLC_CLAUDE_CMD": FAKE}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for _ in range(100):
            try:
                self.get("/api/board")
                return
            except OSError:
                time.sleep(0.1)

    def req(self, path, body=None):
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode() if body is not None else None,
                                   headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r, timeout=20) as f:
                raw, code, hdr = f.read(), f.status, dict(f.headers)
        except urllib.error.HTTPError as e:
            raw, code, hdr = e.read(), e.code, dict(e.headers)
        try:
            return code, json.loads(raw), hdr
        except ValueError:
            return code, raw, hdr

    def get(self, path):
        return self.req(path)

    def post(self, path, body):
        return self.req(path, body)

    def wait_chat(self, id_, n):
        for _ in range(100):
            _, d, _ = self.get("/api/review/chat?id=" + id_)
            if not d.get("pending") and len(d.get("messages", [])) >= n:
                return d
            time.sleep(0.1)
        return d

    def stop(self):
        self.p.terminate()
        self.p.wait(5)


def main():
    root, ch = setup()
    sys.path.insert(0, str(root / ".sdlc" / "bin"))
    from board import Board
    b = Board(root / ".sdlc" / "state" / "board.db")
    b.set_meta(change=ch.name, escalated=["T-1"])
    b.add_item("design", "Trace list screen", key="D-1", status="review")
    b.add_item("task", "Build the ingest endpoint", key="T-1", status="blocked")
    b.event("T-1", "dev-1", "status", "ESCALATED to a human: which retention period?")
    s = Srv(root)
    try:
        run(s, root, ch, b)
    finally:
        s.stop()


def run(s, root, ch, b):
    code, page, _ = s.get("/review")
    check("the review page is served", code == 200 and b"Review" in page)
    _, board_page, _ = s.get("/")
    check("the board has Board | Review tabs", b'data-tab="review"' in board_page and b'id="reviewView"' in board_page)

    _, d, _ = s.get("/api/review")
    ids = {a["id"]: a for a in d.get("artifacts", [])}
    want = {"file:sdlc/ARCHITECTURE.md", "file:sdlc/adr/0001-postgres-first.md", "design:D-1", "escalated:T-1",
            f"file:{ch.relative_to(root).as_posix()}/intent.md"}
    check("artifacts listed (architecture, ADR, design, escalation, intent)", want <= set(ids), str(sorted(ids)))
    check("needs-you count: architecture + design + escalation", d.get("count") == 3, str(d.get("count")))
    _, snap, _ = s.get("/api/board")
    check("board snapshot carries the count for the badge", snap.get("review", {}).get("count") == 3, str(snap.get("review")))

    A = "file:sdlc/ARCHITECTURE.md"
    _, doc, _ = s.get("/api/review/doc?id=" + A)
    check("document, versions and diagram", "Ingestion API" in doc.get("content", "") and len(doc.get("versions", [])) == 1
          and doc.get("diagram") == "sdlc/architecture.svg" and doc.get("editable") is True, json.dumps(doc)[:300])
    code, _, hdr = s.get("/api/review/file?path=sdlc/architecture.svg")
    check("diagram image served with a locked-down CSP", code == 200 and "sandbox" in hdr.get("Content-Security-Policy", ""))
    bad = [s.get("/api/review/file?path=" + p)[0] for p in ("../etc/passwd", "secret.png", "sdlc/ARCHITECTURE.md", "sdlc/../secret.png")]
    check("file endpoint refuses traversal and non-images", all(c == 404 for c in bad), str(bad))
    check("unknown ids are refused", s.get("/api/review/doc?id=file:.sdlc/config.json")[0] == 404
          and s.post("/api/review/chat", {"id": "file:../x.md", "text": "hi"})[0] == 400)

    # chat round trip, then resume of the same session
    s.post("/api/review/chat", {"id": A, "text": "Why a queue?", "quote": "Queue", "section": "Components"})
    c = s.wait_chat(A, 2)
    m = c["messages"]
    check("chat: the architect answers", len(m) == 2 and m[1]["who"] == "architect" and "queue" in m[1]["text"].lower(), str(m))
    calls = [json.loads(x) for x in (root / ".sdlc/state/review/fake-calls.jsonl").read_text().splitlines()]
    check("the architect runs on Opus with the quote in its prompt", "opus" in calls[0]["args"] and "Queue" in calls[0]["prompt"]
          and "Components" in calls[0]["prompt"])
    s.post("/api/review/chat", {"id": A, "text": "Please add a cache in front of reads"})
    c = s.wait_chat(A, 5)
    calls = [json.loads(x) for x in (root / ".sdlc/state/review/fake-calls.jsonl").read_text().splitlines()]
    check("the follow-up resumes the agent's session", "--resume" in calls[1]["args"] and "s1" in calls[1]["args"])
    check("the edit is announced in the chat", any(x.get("changed") for x in c["messages"])
          and "CHANGED" not in c["messages"][3]["text"], str(c["messages"][-2:]))
    _, doc, _ = s.get("/api/review/doc?id=" + A)
    added = [doc["content"].splitlines()[i] for i in doc.get("added", [])]
    check("a 'latest' version appears with the added lines highlighted", doc["version"] == "working" and len(doc["versions"]) == 2
          and any("Redis" in x for x in added) and not any("Ingestion API" in x for x in added), str(added))
    _, old, _ = s.get(f"/api/review/doc?id={A}&ver={doc['versions'][0]['id']}")
    check("the earlier version is still readable", "Redis" not in old.get("content", "x"))

    I = f"file:{ch.relative_to(root).as_posix()}/intent.md"
    s.post("/api/review/chat", {"id": I, "text": "Please add a cache to this"})
    s.wait_chat(I, 2)
    calls = [json.loads(x) for x in (root / ".sdlc/state/review/fake-calls.jsonl").read_text().splitlines()]
    check("an accepted document cannot be edited from chat", "Edit(" not in calls[-1]["args"][calls[-1]["args"].index("--allowedTools") + 1]
          and "Redis" not in (ch / "intent.md").read_text())

    # decisions
    code, r, _ = s.post("/api/review/decide", {"id": "design:D-1", "action": "changes", "text": ""})
    check("request changes needs text", code == 400)
    s.post("/api/review/decide", {"id": "design:D-1", "action": "approve", "text": "ship it"})
    check("design approved through the board", str(b.item("D-1").get("qa_by", "")).startswith("approved"))
    s.post("/api/review/decide", {"id": "escalated:T-1", "action": "resume", "text": "use 30 days"})
    check("escalation resumed with guidance", "T-1" not in b.meta().get("escalated", []) and b.item("T-1")["status"] == "todo")
    code, r, _ = s.post("/api/review/decide", {"id": A, "action": "approve", "text": "good"})
    t = (root / "sdlc/ARCHITECTURE.md").read_text()
    log = sh(root, "git", "log", "--oneline", "-1").stdout
    check("architecture approved, recorded and committed", code == 200 and "Status: approved" in t and "Approved by:" in t
          and "architecture:" in log, str(r) + log)
    time.sleep(3.2)  # the list is cached for 3 s
    _, d, _ = s.get("/api/review")
    check("nothing left waiting", d.get("count") == 0, str([a["id"] for a in d["artifacts"] if a["needs"]]))
    _, doc, _ = s.get("/api/review/doc?id=" + A)
    check("approved architecture is no longer editable", doc.get("editable") is False)


if __name__ == "__main__":
    main()
    print("ALL PASS" if not fails else f"{fails} FAILED")
    sys.exit(1 if fails else 0)
