"""Team mode runs the architect before the planner, and plans nothing until a human approves.
(It used to run only in /sdlc:loop, so /sdlc:team skipped it.) python tests/test_team_architect.py
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
FAKE = json.dumps([sys.executable, str(KIT / "tests" / "fakes" / "fake_team_claude.py")])
fails = 0


def check(name, ok, detail=""):
    global fails
    fails += not ok
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail and not ok else ""))


def repo():
    root = Path(tempfile.mkdtemp(prefix="sdlc-ta-"))
    for c in (["git", "init", "-q", "-b", "main"], ["git", "config", "user.email", "t@x"], ["git", "config", "user.name", "Kunal"]):
        subprocess.run(c, cwd=root)
    subprocess.run([sys.executable, str(KIT / "plugins/sdlc/scripts/init.py"), "--root", str(root)], cwd=root, capture_output=True)
    subprocess.run([sys.executable, str(root / ".sdlc/bin/sdlc.py"), "new", "trace-app"], cwd=root, capture_output=True)
    ch = next((root / "sdlc" / "changes").glob("*trace-app*"))
    (ch / "intent.md").write_text("# Intent\n\nStatus: accepted\n\nBuild a trace app.\n", encoding="utf-8")
    (ch / "spec.md").write_text("# Spec\n\nStatus: accepted\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root); subprocess.run(["git", "commit", "-qm", "setup"], cwd=root)
    return root, ch


def team(root, *args, env=None):
    return subprocess.run([sys.executable, str(root / ".sdlc/bin/team.py"), *args], cwd=root, capture_output=True,
                          text=True, env={**os.environ, "SDLC_CLAUDE_CMD": FAKE, **(env or {})})


def main():
    root, ch = repo()
    doc, bd = root / "sdlc" / "ARCHITECTURE.md", ch / "breakdown.json"

    r = team(root, "plan", "trace-app", "--simulate")
    check("plan runs the architect first and stops before planning", doc.is_file() and not bd.exists()
          and "ARCHITECTURE WAITING FOR A HUMAN" in r.stdout, r.stdout[-400:] + r.stderr[-400:])
    check("the diagram is exported", (root / "sdlc" / "architecture.drawio").is_file())

    r = team(root, "prepare", "trace-app", "--simulate")
    try:
        out = json.loads(r.stdout)
    except ValueError:
        out = {}
    w = (out.get("waiting_for_human") or [{}])[0]
    check("prepare hands the decision to the session lead", w.get("what") == "architecture approval"
          and "architecture-approve" in w.get("approve", "") and not bd.exists(), r.stdout[-400:] + r.stderr[-300:])
    check("open questions are passed on", w.get("open_questions") == ["Retention: 30 or 90 days?"], str(w.get("open_questions")))

    team(root, "architecture-changes", "trace-app", "add a queue in front of the database")
    team(root, "plan", "trace-app", "--simulate")
    check("requested changes reach the architect", "/Queue/" in doc.read_text(encoding="utf-8") and not bd.exists())

    r = team(root, "architecture-approve", "trace-app", "looks right")
    t = doc.read_text(encoding="utf-8")
    adr = (root / "sdlc/adr/0001-postgres-first.md").read_text(encoding="utf-8")
    log = subprocess.run(["git", "log", "--oneline", "-1"], cwd=root, capture_output=True, text=True).stdout
    check("approval is recorded, ADRs accepted, committed", "Status: approved" in t and "Approved by: Kunal" in t
          and "Status: accepted" in adr and "architecture: " in log, t[:300] + log)

    r = team(root, "plan", "trace-app", "--simulate")
    check("after approval the planner runs", bd.is_file(), r.stdout[-300:] + r.stderr[-300:])

    # a self-approved design is reset to proposed: only a human approves
    root2, ch2 = repo()
    team(root2, "plan", "trace-app", "--simulate", env={"FAKE_ARCH": "approved"})
    check("an agent cannot approve its own architecture",
          "Status: proposed" in (root2 / "sdlc/ARCHITECTURE.md").read_text(encoding="utf-8") and not (ch2 / "breakdown.json").exists())

    # nothing to change: planning goes straight on
    root3, ch3 = repo()
    r = team(root3, "plan", "trace-app", "--simulate", env={"FAKE_ARCH": "none"})
    check("no architectural change: the plan goes ahead", (ch3 / "breakdown.json").is_file()
          and not (root3 / "sdlc/ARCHITECTURE.md").exists(), r.stderr[-300:])

    print("ALL PASS" if not fails else f"{fails} FAILED")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
