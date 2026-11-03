---
name: design
description: Design the UI for an accepted change before it is built — greenfield (sets DESIGN.md) or brownfield (follows the existing design) — with the impeccable skill, as an HTML mockup the user approves. Skipped for backend-only changes.
argument-hint: "<change> [--greenfield|--brownfield]"
disable-model-invocation: true
---
> Windows: where this says `python3`, use `python` (or `py -3`) if `python3` is missing or opens the Microsoft Store.


# /sdlc:design — design first, then build

Change: `$ARGUMENTS` (change folder or substring; empty → the single change at stage `plan-ready`/`plan`/`build` from `python3 .sdlc/bin/sdlc.py status`).

## 1. Does this change need design?
Read intent.md, spec.md and plan.md. If nothing a user sees changes (API, jobs, data, infra only), say "no UI in this change — no design needed" and stop. `.sdlc/config.json` `team.design.mode` can force `always` or `never`.

## 2. Greenfield or brownfield?
- **Brownfield**: `DESIGN.md` exists, or the repo already has UI files (templates, components, CSS, pages). The existing look is the standard; new screens must look like they always belonged. Do not redesign, re-theme or change existing tokens.
- **Greenfield**: no UI yet; this design sets the standard.
`--greenfield` / `--brownfield` in the arguments overrides the detection. Tell the user which one you picked and why, in one line.

## 3. Design with the impeccable skill
Load the **impeccable** skill with the Skill tool and follow its Setup (context loading), then:
- **Greenfield**: run its `init` flow to write PRODUCT.md (ask the user its questions here — this session is interactive), treat the work as new: choose a direction and write DESIGN.md, then its `shape` flow for each screen.
- **Brownfield**: if DESIGN.md is missing, run its `document` flow to generate DESIGN.md from the existing code first; then `shape` the new screens only, reusing existing tokens and components.
If impeccable is not installed, say so in one line and suggest `/plugin marketplace add pbakaus/impeccable` then `/plugin install impeccable@impeccable`; if the user wants to continue without it, apply the same discipline yourself.

## 4. Deliverables (in the change folder)
1. `DESIGN.md` at the repo root — created (greenfield) or extended with only the new patterns (brownfield).
2. `<change>/design/mockup.html` — one self-contained HTML file with every screen and state: default, filled, empty, loading, validation/error, hover/focus, at desktop width and inside a 390px mobile frame. Real copy from the spec. DESIGN.md tokens as CSS variables.
3. `<change>/design/design-notes.md` — direction, screens, components, tokens, interactions, accessibility, assumptions, and which plan step / task builds which part.
Look at the mockup in a browser (Playwright or the browser tool) at 1280px and 390px; run impeccable's `critique` and `audit` on it if available and fix the findings.

## 5. The user approves
Show the user the mockup: give the file path (and a screenshot if you can take one). Then AskUserQuestion:
"Is this design good to build?" — **Approve (Recommended)** / **Change something** / **Stop**.
- *Change something*: ask what, update the design, ask again.
- *Approve*: commit `design: <slug>` (DESIGN.md, PRODUCT.md, design folder). Building now follows the mockup: `/sdlc:build` or `/sdlc:team` tell developers to match it and QA to compare the page against it.

With the agent team (`/sdlc:team`), this same step runs automatically as task **D-1**: a designer agent produces the mockup, the board shows **Approve / Request changes**, and only UI tasks wait for it.
