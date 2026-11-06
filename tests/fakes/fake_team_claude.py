"""Scripted stand-in for a headless team agent (`claude -p --output-format stream-json`, prompt on stdin).
Only the architect is scripted; anything else just reports done.
  FAKE_ARCH=none       the architect replies NO ARCHITECTURE CHANGE
  FAKE_ARCH=approved   the architect (wrongly) marks its own design approved: the lead must reset it to proposed
"""
import json
import os
import sys
from pathlib import Path

prompt = sys.stdin.read()
root = Path.cwd()
out = "done"
if "You are the architect" in prompt:
    mode = os.environ.get("FAKE_ARCH", "propose")
    if mode == "none":
        out = "NO ARCHITECTURE CHANGE: the change adds no component"
    else:
        revised = "asked for these changes" in prompt
        (root / "sdlc" / "adr").mkdir(parents=True, exist_ok=True)
        (root / "sdlc" / "ARCHITECTURE.md").write_text(
            "# Trace app — architecture\n\nStatus: " + ("approved" if mode == "approved" else "proposed") + "\n\n"
            "## Diagram\n\n```mermaid\nflowchart LR\n  app((App)) --> api[API]\n  api --> db[(Postgres)]\n"
            + ("  api --> q[/Queue/]\n" if revised else "") + "```\n\n## Decisions\n\n- ADR-0001 Postgres first\n\n"
            "## Open questions\n\n- [ ] Retention: 30 or 90 days?\n", encoding="utf-8")
        (root / "sdlc" / "adr" / "0001-postgres-first.md").write_text(
            "# ADR-0001 Postgres first\n\nStatus: proposed\n\nDecision: Postgres.\n", encoding="utf-8")
        out = "Proposed: API + Postgres" + (" + queue (revised)" if revised else "")
print(json.dumps({"type": "result", "result": out, "is_error": False, "total_cost_usd": 0.0}), flush=True)
