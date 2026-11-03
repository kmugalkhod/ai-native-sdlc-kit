---
name: triage
description: Stage 6 Maintain — diagnose an alert, band breach, incident message or ticket read-only, act only through allowed routes, and write the finding back into the loop as intent.md (or a small PR through review).
argument-hint: "<alert text, metric, ticket or channel message> [--headless] [--alert '<json from monitor>']"
disable-model-invocation: true
---
> Windows: where this says `python3`, use `python` (or `py -3`) if `python3` is missing or opens the Microsoft Store.


# /sdlc:triage — the loop closes: findings re-enter as intent.md

Input: `$ARGUMENTS`

When called by `monitor.py` the input contains `--alert` JSON with: metric, tier, action (`diagnose` | `propose`), rules fired, stats (mean, std, recent values, z-scores), owner, allowed_routes, runbooks. Respect them exactly: your tools were already scoped to the tier.

## 1. Diagnose (always read-only)
- Read `sdlc/lessons/` first — a repeat incident starts from what was learnt.
- Correlate the breach window with recent changes: `git log --since`, recent merges/deploys, CI runs (`gh run list/view`, `glab ci`), relevant code paths, `sdlc/changes/*` merged in the window.
- Form the most likely cause with the evidence that supports it, plus at least one alternative you ruled out and why.

## 2. Act — only through gated routes
- `diagnose` tier / interactive default: no changes to code, config or infrastructure.
- `propose` tier: you may (a) open a **small, well-bounded** fix as a branch + PR/MR into the normal review gate (revert, flaky-test quarantine, config fix), or (b) run a runbook listed in `runbooks`, **exactly** as written — nothing else. Never deploy to production; the production gate stands.
- Interactive (incident channel / user present): propose the action and wait for an explicit "go" before running any runbook or rollback.

## 3. Write it back into the loop
Create the intent: `python3 .sdlc/bin/sdlc.py new <metric-or-incident-slug> --title "<title>"` and fill it in Stage 1 format:
- **Problem**: the anomaly and its evidence (metric, values vs band, rules fired, time window, links).
- **Proposed outcome**: what "back to normal" and "never again" look like.
- **Affected users and systems**.
- **Constraints**, **Open questions** (incl. alternatives not yet ruled out).
- Status stays `draft` — the service owner / on-call triages it: fix now, schedule, or dismiss (dismissals tune the bands).
If you opened a PR or ran a runbook, link it in the intent.

## 4. After a fix ships (when asked)
- Write `sdlc/lessons/YYYY-MM-<slug>.md` (what happened, detection, diagnosis, action and who authorised it, fix PR, eval added).
- Add the regression eval: `/sdlc:evals add`.
- Verify the metric is back inside its band (`python3 .sdlc/bin/monitor.py --metric <m> --dry-run`) and state it.

With `--headless`: no questions; end with a 3-line summary: cause, action taken (or none), path of the intent.md.
