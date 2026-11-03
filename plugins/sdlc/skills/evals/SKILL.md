---
name: evals
description: Run the agent-configuration eval suite, or add a new eval case from a recent task, PR or production incident.
argument-hint: "run [--case ID] | add <task, PR, or incident>"
disable-model-invocation: true
---
> Windows: where this says `python3`, use `python` (or `py -3`) if `python3` is missing or opens the Microsoft Store.


# /sdlc:evals

Arguments: `$ARGUMENTS`

## run
`python3 .sdlc/bin/evals.py [--case ID] --json .sdlc/eval-results.json` — each case runs `claude -p` in a throwaway worktree with the current CLAUDE.md/.claude config. This spends model budget; with no `--case`, tell the user how many cases will run and ask before starting. Report pass rate vs threshold and each failing check with its reason. When a config change dropped the pass rate, say which change is the likely cause.

## add
Create `evals/cases/<id>.json` (see `evals/README.md` for the shape):
- **prompt**: the real task as it was asked (from the PR description, ticket, or the incident's intent.md).
- **ref**: the commit *before* the accepted solution, so the task is unsolved at start.
- **checks**: commands that define acceptable — the tests added by the accepted fix, lint, a grep for the policy, behaviour unchanged.
- **must_not_change**: test files, generated code, `.sdlc/**`.
- **allowed_tools**: the minimum needed.
For incidents: id `incident-<yyyy-mm>-<slug>`, written with the owning team, never deleted — it is a permanent regression test.
Validate the JSON (`python3 -m json.tool`), then offer to run just that case once.
