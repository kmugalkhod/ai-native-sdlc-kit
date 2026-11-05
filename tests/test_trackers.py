"""Mock Jira + Linear servers; run the Sync engine against them and check the calls."""
import json, os, sys, threading, tempfile, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "plugins/sdlc/scripts"))

CALLS = []
JC, LC = {}, {}  # comments per Jira issue key / Linear issue id
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, obj, code=200):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type","application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def _body(self):
        n = int(self.headers.get("Content-Length") or 0); return json.loads(self.rfile.read(n) or b"{}")
    def do_GET(self):
        CALLS.append(("GET", self.path, None, self.headers.get("Authorization")))
        if self.path == "/rest/api/3/myself":
            return self._send({"accountId": "bot"})
        m = re.match(r"/rest/api/3/issue/([^/]+)/comment", self.path)
        if m:
            return self._send({"comments": JC.get(m.group(1), [])})
        if self.path.endswith("/transitions"):
            return self._send({"transitions":[{"id":"11","name":"Start","to":{"name":"In Progress"}},
                                               {"id":"21","name":"In Review","to":{"name":"In Review"}},
                                               {"id":"31","name":"Done","to":{"name":"Done"}}]})
        self._send({})
    def do_PUT(self):
        CALLS.append(("PUT", self.path, self._body(), self.headers.get("Authorization"))); self.send_response(204); self.end_headers()
    def do_POST(self):
        body = self._body(); CALLS.append(("POST", self.path, body, self.headers.get("Authorization")))
        if self.path == "/rest/api/3/issue":
            n = sum(1 for c in CALLS if c[0]=="POST" and c[1]=="/rest/api/3/issue")
            return self._send({"id": str(n), "key": f"PROJ-{n}"}, 201)
        m = re.match(r"/rest/api/3/issue/([^/]+)/comment$", self.path)
        if m:
            JC.setdefault(m.group(1), []).append({"id": str(len(JC[m.group(1)]) + 100), "author": {"accountId": "bot"},
                                                  "body": body["body"], "created": "2026-01-01T00:00:00Z"})
            return self._send({}, 201)
        if self.path == "/graphql":
            q = body["query"]
            if "viewer{id}" in q:
                return self._send({"data": {"viewer": {"id": "me"}, "issue": {"comments": {"nodes": LC.get(body["variables"]["id"], [])}}}})
            if "commentCreate" in q:
                i = body["variables"]["i"]
                LC.setdefault(i["issueId"], []).append({"id": f"c{len(LC[i['issueId']])}", "body": i["body"], "user": {"id": "me"}})
                return self._send({"data": {"commentCreate": {"success": True}}})
            if "teams(" in q: return self._send({"data":{"teams":{"nodes":[{"id":"team1","key":"ENG","states":{"nodes":[{"id":"s1","name":"Todo"},{"id":"s2","name":"In Progress"},{"id":"s3","name":"In Review"},{"id":"s4","name":"Done"}]}}]}}})
            if "projectCreate" in q: return self._send({"data":{"projectCreate":{"success":True,"project":{"id":"p1","url":"https://linear.app/x/project/p1"}}}})
            if "issueCreate" in q:
                n = sum(1 for c in CALLS if c[1]=="/graphql" and "issueCreate" in c[2]["query"])
                return self._send({"data":{"issueCreate":{"success":True,"issue":{"id":f"i{n}","identifier":f"ENG-{n}","url":f"https://linear.app/x/issue/ENG-{n}"}}}})
            if "issueLabels(" in q: return self._send({"data":{"issueLabels":{"nodes":[]}}})
            if "issueLabelCreate" in q: return self._send({"data":{"issueLabelCreate":{"issueLabel":{"id":"lab1"}}}})
            return self._send({"data":{"ok":True}})
        self._send({}, 201)

srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_port}"

from board import Board
import trackers

def seed(b):
    e = b.add_item("epic", "Bookmarks app", description="Save and find links")
    s = b.add_item("story", "Save a bookmark", e, acceptance=["POST /api/bookmarks returns 201"])
    t = b.add_item("task", "API endpoint", s)
    return e, s, t

ok = True
def check(cond, msg):
    global ok; print(("PASS " if cond else "FAIL ") + msg); ok &= bool(cond)

# ---------------- Jira
os.environ.update(JIRA_BASE_URL=base, JIRA_EMAIL="bot@example.com", JIRA_API_TOKEN="tok")
b = Board(tempfile.mktemp(suffix=".db")); e, s, t = seed(b)
j = trackers.Jira({"project_key": "PROJ"}); sync = trackers.Sync(b, j)
sync.run()
creates = [c for c in CALLS if c[1] == "/rest/api/3/issue"]
check(len(creates) == 3, "jira: epic, story, subtask created")
check(creates[0][2]["fields"]["issuetype"]["name"] == "Epic" and creates[2][2]["fields"]["issuetype"]["name"] == "Subtask", "jira: issue types")
check(creates[1][2]["fields"]["parent"] == {"key": "PROJ-1"} and creates[2][2]["fields"]["parent"] == {"key": "PROJ-2"}, "jira: parent links epic>story>subtask")
check(creates[0][3].startswith("Basic "), "jira: basic auth header")
CALLS.clear()
b.update(t, "lead", status="in_progress", assignee="dev-1"); sync.run()
check(any(c[0]=="PUT" and c[2] and c[2].get("update",{}).get("labels")==[{"add":"agent-dev-1"}] for c in CALLS), "jira: agent label on assign")
check(any(c[1].endswith("/transitions") and c[0]=="POST" and c[2]=={"transition":{"id":"11"}} for c in CALLS), "jira: transition to In Progress")
CALLS.clear()
b.update(t, "dev-1", note="API done, 6 tests pass", status="in_qa"); b.event(t, "qa-1", "qa", "PASS: browser test ok"); sync.run()
check(any(c[0]=="POST" and c[2]=={"transition":{"id":"21"}} for c in CALLS), "jira: transition to In Review on QA hand-off")
coms = [c for c in CALLS if c[1].endswith("/comment")]
check(len(coms) == 2 and "[qa-1] PASS" in json.dumps(coms), "jira: hand-off + QA comments posted")
CALLS.clear(); sync.run()
check(not CALLS or all(c[0]=="GET" for c in CALLS), "jira: idempotent second run (no new writes)")

# reply-to-resume: an escalated task asks on the issue; a human's reply there resumes it
b.update(t, "lead", note="ESCALATED to a human: which date format does the API expect?", status="blocked")
b.set_meta(escalated=[t]); ext = b.item(t)["ext_key"]; sync.run()
asks = [c for c in JC.get(ext, []) if "sdlc-ask" in json.dumps(c)]
check(len(asks) == 1 and "which date format" in json.dumps(asks), "jira: escalation asked as a comment on the issue")
sync.run(); check(t in b.meta().get("escalated", []), "jira: no reply yet → still escalated (its own question doesn't count)")
JC[ext].append({"id": "900", "author": {"accountId": "kunal", "displayName": "Kunal"}, "created": "2026-01-01T01:00:00Z",
                "body": {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Use ISO 8601 dates"}]}]}})
sync.run()
hist = json.dumps(b.events(item_key=t, limit=50))
check(t not in b.meta().get("escalated", []) and "Use ISO 8601 dates" in hist and b.item(t)["status"] != "blocked",
      "jira: the reply resumed the task with it as guidance")

# ---------------- Linear
os.environ.update(LINEAR_API_KEY="lin_api_x", LINEAR_API_URL=base + "/graphql"); CALLS.clear()
b2 = Board(tempfile.mktemp(suffix=".db")); e2, s2, t2 = seed(b2)
lsync = trackers.Sync(b2, trackers.Linear({"team_key": "ENG"})); lsync.run()
qs = [c[2]["query"] for c in CALLS if c[1]=="/graphql"]
check(any("projectCreate" in q for q in qs), "linear: epic -> project")
ic = [c[2]["variables"]["i"] for c in CALLS if c[1]=="/graphql" and "issueCreate" in c[2]["query"]]
check(len(ic) == 2 and ic[0].get("projectId") == "p1" and ic[1].get("parentId") == "i1" and ic[1].get("projectId") == "p1", "linear: story in project, task is sub-issue")
check(all(c[3] == "lin_api_x" for c in CALLS), "linear: API key header")
CALLS.clear(); b2.update(t2, "lead", status="in_progress", assignee="dev-2"); lsync.run()
qs = [c[2] for c in CALLS if c[1]=="/graphql"]
check(any("issueAddLabel" in q["query"] for q in qs) and any("issueLabelCreate" in q["query"] for q in qs), "linear: agent label created + added")
check(any("issueUpdate" in q["query"] and q["variables"]["i"].get("stateId")=="s2" for q in qs), "linear: state -> In Progress")
b2.set_meta(escalated=[t2]); b2.update(t2, "lead", note="ESCALATED to a human: unclear scope", status="blocked"); lsync.run()
lid = b2.item(t2)["ext_key"]
check(any("sdlc-ask" in c["body"] for c in LC.get(lid, [])), "linear: escalation asked as a comment")
LC[lid].append({"id": "c99", "body": "Only the API, no UI", "user": {"id": "u-kunal", "name": "Kunal"}}); lsync.run()
check(t2 not in b2.meta().get("escalated", []) and "Only the API" in json.dumps(b2.events(item_key=t2, limit=50)),
      "linear: the reply resumed the task")
print("ALL PASS" if ok else "SOME FAILED"); srv.shutdown(); sys.exit(0 if ok else 1)
