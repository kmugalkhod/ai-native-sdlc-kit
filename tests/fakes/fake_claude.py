"""A scripted stand-in for `claude -p`, so the out-of-the-loop pipeline runs end to end in CI without a model.

It does what each stage's real agent would leave behind, steered by environment variables:
  FAKE_FILES       JSON {path: content} the build stage writes (default: app.txt = "ok")
  FAKE_CONFIDENT   "1" (default) or "0": what the assessment reports
  FAKE_NO_ASSESS   "1": the assessment step writes nothing
It prints the same JSON shape as `claude -p --output-format json`.
"""
import json
import os
import re
import sys
from pathlib import Path

args = sys.argv[1:]
prompt = args[args.index("-p") + 1] if "-p" in args else ""
root = Path.cwd()
out = "done"


def write(rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


m = re.match(r"/sdlc:(\w+) (\S+)", prompt)
if m and m.group(1) == "spec":
    write(f"{m.group(2)}/spec.md", "# Spec\n\nStatus: draft\n\n## Acceptance criteria\n\n- AC-1 it works\n")
elif m and m.group(1) == "plan":
    write(f"{m.group(2)}/plan.md", "# Plan\n\nStatus: draft\n\n## Steps\n\n1. build it\n")
elif m and m.group(1) == "build" or prompt.startswith("Verification failed"):
    for rel, text in json.loads(os.environ.get("FAKE_FILES") or '{"app.txt": "ok\\n"}').items():
        write(rel, text)
elif m and m.group(1) == "review":
    write(f"{m.group(2)}/review.md", "# Review\n\nImportant: 0\nNits: 0\n")
elif prompt.startswith("Write the hidden holdout scenarios for the change"):
    name = re.match(r"Write the hidden holdout scenarios for the change (\S+):", prompt).group(1)
    if os.environ.get("SDLC_HOLDOUT_ACCESS") == "1":  # the pipeline grants the writer access, nobody else
        write(f"sdlc/holdout/{name}.md", "## H-1 an empty title is refused with a clear error message\n"
              "Touches: creating a post\nSteps: post with an empty title, then list all posts afterwards\n"
              "Expect: a 400 response and the list of posts is exactly as long as before the attempt\n")
elif prompt.startswith("Verify the change") and "hidden holdout" in prompt:
    ok = os.environ.get("SDLC_HOLDOUT_ACCESS") == "1" and os.environ.get("FAKE_HOLDOUT", "pass") == "pass"
    out = ("H-1: " + ("pass" if ok else "fail") + "\n" + json.dumps({"verdict": "pass" if ok else "fail", "results": [
        {"id": "H-1", "pass": ok, "observed": "400, list unchanged" if ok else "201, an empty post was created"}]}))
elif prompt.startswith("Gate the"):
    out = 'Looks safe.\n{"verdict":"pass","reasons":["scripted gate"]}'
elif prompt.startswith("Assess the change at"):
    rel = re.match(r"Assess the change at (\S+) ", prompt).group(1)
    if os.environ.get("FAKE_NO_ASSESS") != "1":
        sure = os.environ.get("FAKE_CONFIDENT", "1") == "1"
        write(f"{rel}/assessment.json", json.dumps({
            "confident": sure, "recommendation": "merge" if sure else "handover",
            "reason": "" if sure else "intent.md does not say what happens on an empty title",
            "assumptions": ["titles are plain text"], "notes": ""}, indent=2))
print(json.dumps({"result": out, "is_error": False, "total_cost_usd": 0.0}))
