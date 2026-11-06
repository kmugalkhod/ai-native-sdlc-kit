"""Stands in for `claude -p --output-format json` in the Review room tests. Answers questions; when asked to change
something and it was allowed to edit, edits sdlc/ARCHITECTURE.md like the architect would. Records each call."""
import json
import sys
from pathlib import Path

args = sys.argv[1:]
prompt = sys.stdin.read()
log = Path(".sdlc/state/review/fake-calls.jsonl")
log.parent.mkdir(parents=True, exist_ok=True)
with log.open("a", encoding="utf-8") as f:
    f.write(json.dumps({"args": args, "prompt": prompt}) + "\n")

resumed = "--resume" in args
tools = args[args.index("--allowedTools") + 1] if "--allowedTools" in args else ""
reply = ("(resumed) " if resumed else "") + "The ingestion API writes to the queue first, so spikes do not hit Postgres."
if "add a cache" in prompt.lower() and "Edit(sdlc/ARCHITECTURE.md)" in tools:
    p = Path("sdlc/ARCHITECTURE.md")
    p.write_text(p.read_text(encoding="utf-8") + "\n## Cache\n\nA Redis cache sits in front of the read API.\n", encoding="utf-8")
    reply += "\nCHANGED: added a Redis cache section"
print(json.dumps({"type": "result", "result": reply, "session_id": "s1", "total_cost_usd": 0.01, "is_error": False}))
