---
name: sdlc-artifacts
description: Conventions for the AI-native SDLC artifacts. Use whenever reading, writing or reasoning about intent.md, spec.md, plan.md, review.md, ESCALATION.md, lessons, or anything under sdlc/changes/ or .sdlc/.
---
> Windows: where this says `python3`, use `python` (or `py -3`) if `python3` is missing or opens the Microsoft Store.


# AI-native SDLC artifact conventions

The thread through the loop is the committed artifact: each stage ends by committing one, the next stage starts by reading it, and the chain of commits is the audit trail (who asked, what the agent produced, who approved).

## Layout
```
sdlc/changes/<YYYY-MM-DD>-<slug>/
  intent.md      Stage 1  what is wanted, why, constraints — originator's words   (product owner accepts)
  spec.md        Stage 2  requirements + design + flagged concerns                 (product owner accepts)
  plan.md        Stage 3  files, order, tests, risks, alternatives, deviations     (engineer / tech lead accepts)
  review.md      Stage 5  severity-ranked findings, tally line                     (informs code owner)
  ESCALATION.md  any      written by the headless loop when a gate hands off to a human
sdlc/lessons/    Stage 6  post-mortems future triage reads
.sdlc/           human-owned: config.json (gates), templates/, bin/ (CLI), state/ (fix mode, approvals)
```

## Status lines
Each artifact's header carries `Status:`. Lifecycle: `draft → accepted | rejected`; plan.md continues `accepted → implemented`. Only the named human role sets `accepted`, except in the headless loop where the gatekeeper agent does and records it in an HTML comment.
`python3 .sdlc/bin/sdlc.py status` infers each change's stage from which files exist and their Status.

## Rules
- Never skip a stage's artifact for non-trivial work. Trivial fixes may go intent → plan; say so in plan.md.
- Templates live in `.sdlc/templates/` (org-owned). Fill every section; delete HTML comment guidance once filled.
- Link, don't duplicate: if Jira/GitLab/GitHub holds the record, put the id in `Record:` and write the artifact's commit SHA back to the record.
- spec.md flagged concerns: `- [ ]` needs a policy owner's decision (blocks build), `- [~] ASSUMED:` visible assumption (non-blocking), `- [x]` resolved with owner + decision.
- plan.md must match the code: a deviation updates plan.md in the same commit and adds a Deviations line.
- review.md tally line is machine-read: `Important: <n> · Nit: <n> · Pre-existing: <n>`.
- Measure from git: intent→spec time, spec rework after plan, plan revisions, survival rate (`sdlc.py metrics`).
