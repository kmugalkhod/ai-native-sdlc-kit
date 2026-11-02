---
name: status
description: Show where every change sits in the AI-native SDLC loop, what the next step is, and the playbook's leading/lagging indicators computed from git history.
argument-hint: "[--metrics]"
disable-model-invocation: true
---

# /sdlc:status

Run:
```bash
python3 .sdlc/bin/sdlc.py status
python3 .sdlc/bin/sdlc.py metrics      # only if $ARGUMENTS contains --metrics, or the user asks how it's going
```
Also check for `ESCALATION.md` files under `sdlc/changes/` and `python3 .sdlc/bin/sdlc.py fix-mode status`.

Reply with a compact table (change · stage · next step), then one line each for: escalations waiting on a human, fix mode on/off, and — with metrics — median intent→spec hours, spec rework after plan, intent survival rate. No commentary beyond what needs action.
