---
name: bugfix
description: Stage 4 Test — fix a bug failing-test-first. Reproduce it as a test, confirm it fails for the expected reason, commit the test, lock test files with fix mode, then make it pass without touching the test.
argument-hint: "<bug description, ticket id, or log excerpt>"
disable-model-invocation: true
---
> Windows: where this says `python3`, use `python` (or `py -3`) if `python3` is missing or opens the Microsoft Store.


# /sdlc:bugfix — the test that existed before the fix is the proof

Bug: `$ARGUMENTS`

## 1. Reproduce as a test
- Read the report (ticket via CLI/connector if given), logs, and the code path. State the hypothesised cause in one sentence.
- Write the smallest test that reproduces the bug in the project's existing test style and location.
- Run it. It must **fail, and for the reason you expect** (assertion on the buggy behaviour — not an import error or typo). If it passes or fails for another reason, the reproduction is wrong: revise it.
- Show the user the failing output.

## 2. Commit the test, then lock it
```bash
git add <test file> && git commit -m "test: reproduce <short bug>"
python3 .sdlc/bin/sdlc.py fix-mode on --lock <test file>
```
Fix mode makes the hooks block every edit (tool or shell) to test files. Only a human can turn it off.

## 3. Fix the code
- Change production code only. Run the new test, then the full `python3 .sdlc/bin/sdlc.py verify`.
- If you believe the test itself is wrong, stop and explain to the user — do not attempt to edit it.
- If the bug belongs to a tracked change, add a Deviations line in that change's plan.md.

## 4. Finish
- Commit the fix: `git commit -m "fix: <short bug>"`.
- Tell the user to release the lock in **their own terminal**: `python3 .sdlc/bin/sdlc.py fix-mode off`.
- If this came from a production incident: propose an eval case in `evals/cases/` (`/sdlc:evals add`) and a lessons entry.
