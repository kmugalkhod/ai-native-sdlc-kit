---
name: build
description: Stage 3/4 Build+Test — implement an accepted plan.md with a feedback loop (verify until green), keep plan.md in sync with deviations, then hand off to the verifier and simplifier agents.
argument-hint: "<change folder or substring> [--headless]"
disable-model-invocation: true
---

# /sdlc:build — implement against the plan, prove it with the toolchain

Change: `$ARGUMENTS` (resolve to one folder under `sdlc/changes/`; if empty, pick the single change at stage `build` from `python3 .sdlc/bin/sdlc.py status` or ask).

## Preconditions
plan.md has `Status: accepted`. If it does not, stop: nothing is implemented without an accepted plan.

## Branch
If on a protected branch (see `.sdlc/config.json`), create `sdlc/<change-folder>` first (`git checkout -b`). The agent never pushes to main.

## Implement
1. Follow plan.md's **Order of work** step by step. After each step run the narrowest relevant check, then move on.
2. Tests named in **Tests that prove it** are written with the code (bug fixes: test first — use `/sdlc:bugfix` instead).
3. The feedback loop is the definition of done: `python3 .sdlc/bin/sdlc.py verify` must be fully green (build, test, lint). If it fails, fix the **code**, never the test, never skip/delete a failing test. Iterate.
4. UI work: if a browser/screenshot tool is available, compare against the mock in spec.md; 2–3 rounds is normal.
5. Hooks will block protected paths, governance files, secrets and production actions. A block is a boundary, not an obstacle: change approach or tell the user what approval is needed. Never try to work around a hook.

## Keep plan.md honest
Whenever the implementation departs from the plan (different file, extra step, changed approach), update plan.md in the **same commit**: fix the affected section and append a line under **Deviations** (`date — what — why`). At the end set `Status: implemented`.

## Before reporting done
1. Run the `sdlc:verifier` agent (fresh context, reports only) — pass it the change folder.
2. Optionally run `sdlc:simplifier` on the changed files, then re-verify.
3. Paste the final `verify` output.
4. Commit in logical commits: `git commit -m "<type>(<slug>): <what>"` — code, tests and any plan.md update together.

## Report
Files changed, verify output summary, deviations from plan, anything the verifier flagged. Next: `/sdlc:review`.

With `--headless`: no questions; make the most reasonable choice, record it under Deviations, and commit only if `.sdlc/config.json` pipeline.commit is true.
