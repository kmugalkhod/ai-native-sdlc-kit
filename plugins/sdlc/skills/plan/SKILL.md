---
name: plan
description: Stage 3 Build (plan mode) — read the accepted spec and the codebase without changing code, interview the engineer, and produce plan.md (files, order of work, tests that prove it, risks, alternatives).
argument-hint: "<change folder or substring> [--headless]"
disable-model-invocation: true
---
> Windows: where this says `python3`, use `python` (or `py -3`) if `python3` is missing or opens the Microsoft Store.


# /sdlc:plan — nothing is implemented without an accepted plan

Change: `$ARGUMENTS` (resolve to one folder under `sdlc/changes/`; if empty, pick the single `plan-ready` change from `python3 .sdlc/bin/sdlc.py status` or ask).

**Rule for this skill: do not modify any source file.** The only file you write is the change's `plan.md`. If the session is not already in plan mode, tell the user they can press Shift+Tab to enter it for the interview, and behave as if it were on.

## Preconditions
spec.md exists with `Status: accepted` and no `- [ ]` flagged concerns. Otherwise stop and say what is missing.
If `sdlc/ARCHITECTURE.md` exists, it must be `Status: approved`. A `proposed` architecture goes to the user first
(**architect** skill). (Small changes without a spec: intent.md accepted is enough — say so in the plan header.)

## Do
1. Read intent.md, spec.md, CLAUDE.md, sdlc/ARCHITECTURE.md (if it exists: plan within it), and every file the change will touch plus its tests and callers. Use `sdlc:researcher` for broad sweeps.
2. Draft the plan from `.sdlc/templates/plan.md`:
   - **Files that change** — path, new/modified, why.
   - **Dependencies** — every new package with a version constraint and the manifest it goes in; `None` if none. Prefer the standard library and packages already in use.
   - **Order of work** — small steps, each leaving the build green.
   - **Tests that prove it** — test files and cases mapped to the spec's acceptance criteria; for bug fixes the failing test comes first.
   - **Architecture fit**: which components from ARCHITECTURE.md this touches. If the plan needs a component, data
     store, queue or external service that is not there, stop and send the change back to the **architect** skill.
     Never plan around the architecture.
   - **Risks** — what it could break, the riskiest step, mitigation (rate limits, migrations, auth, data).
   - **Alternatives considered** — what you chose not to do and why.
   - **Verification target** — quantifiable done: commands that must pass, response shapes, screenshot vs mock.
3. Interrogate your own plan with the engineer (interactive): What could this break? Which step is riskiest? What else could we do? Iterate until an engineer who never saw this conversation could implement it from plan.md alone.

With `--headless`: no interview; answer those three questions yourself inside Risks/Alternatives.

## Gate
The engineer accepts (tech lead/architect for anything the org classes higher-risk) by setting `Status: accepted` and `Accepted by: <name>`. Then commit: `git add <change>/plan.md && git commit -m "plan: <slug>"`. Next: `/sdlc:build`.
