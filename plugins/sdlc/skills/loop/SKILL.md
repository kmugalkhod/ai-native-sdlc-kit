---
name: loop
description: The whole AI-native SDLC in one interactive command. Sets up the repo if needed, then runs intent → spec → plan → build+test → review for an idea, pausing only for one-click human gates, committing each artifact, and asking for the next idea when done.
argument-hint: "<idea, e.g. 'todo app with FastAPI'> [--auto]"
disable-model-invocation: true
---
> Windows: where this says `python3`, use `python` (or `py -3`) if `python3` is missing or opens the Microsoft Store.


# /sdlc:loop — one command, the whole loop, interactive

Idea: `$ARGUMENTS`

You run every stage yourself in this session. The user should never need a terminal, sed, or manual commits. Their job is to answer questions and click the gates.

**Stage instructions live in the other skills. Read each one when you reach its stage and follow it, with the overrides below.**
`${CLAUDE_PLUGIN_ROOT}/skills/<stage>/SKILL.md` for init, intent, spec, architect, plan, build, review.

**Gate rule.** At each gate use AskUserQuestion with one question and these options:
- **Accept (Recommended)**
- **Change something**
- **Stop here**

Put a 3–6 line summary of the artifact in the question text, not the whole file. On *Change something*, ask what to change, apply it, and ask the gate again. On *Stop here*, commit what exists and tell the user to re-run `/sdlc:loop` on the same idea to resume.

**`--auto`.** Skip the spec, plan and review gates: the `sdlc:gatekeeper` agent decides instead, and its verdict is shown in one line. The intent gate and the architecture gate always stay with the user, as does any spec concern marked `- [ ]`.

Keep a task list (TaskCreate/TaskUpdate) with these items: Setup · Intent · Spec · Architecture · Plan · Build & test · Review · Done. Tick each one off as it finishes. Between stages, say one short line about what you're starting. No long narration.

---

## 0. Setup (only if needed)
- Not a git repo → `git init -b main`.
- No `.sdlc/config.json` → follow the **init** skill.
  - For an empty or new project, infer the stack from the idea. If the idea doesn't say, ask ONE AskUserQuestion with 2–4 sensible stacks, for example "Python + FastAPI + SQLite + pytest (Recommended)" or "Node + Express + Vitest".
  - Choose setup/test/lint commands that use a project virtualenv or a local install, using the paths for the current OS (Windows: `.venv\Scripts\…`).
  - Commit with `chore: adopt AI-native SDLC`.
- Already set up → skip silently.
- If a change folder for this idea already exists (`python3 .sdlc/bin/sdlc.py status`), resume from its current stage. Do not start over.

## 1. Intent → gate
- Follow the **intent** skill, but ask at most ONE round of clarifying questions, using AskUserQuestion with up to 4 questions and offering sensible defaults. If the idea is already clear, ask none and record your assumptions under Open questions as `ASSUMED:`.
- Create the folder with `python3 .sdlc/bin/sdlc.py new <slug>`, then fill in intent.md.
- **Gate (always the user's call):** "Accept this intent?"
  - On Accept: set `Status: accepted`, then `git checkout -b sdlc/<change-folder>` and commit `intent: <slug>`.

## 2. Spec → gate
- Follow the **spec** skill.
- Resolve every `- [ ]` concern with the user, one AskUserQuestion per concern (options: the candidate decisions). Record each as `- [x] … — decided by <user>`.
- **Gate:** "Accept this spec?" On Accept: set `Status: accepted` and commit `spec: <slug>`.

## 2b. Architecture → gate (new projects and architectural changes only)
Follow the **architect** skill. It runs when the repo has no `sdlc/ARCHITECTURE.md` and the change is a new product or
a sizeable feature, or when the spec adds or changes a component, data store, queue, external service, public API,
auth model or deployment unit. Otherwise skip it with one line: "architecture unchanged".
- **Gate (always the user's call):** "Approve this architecture?"
  - On Approve: set `Status: approved` and `Approved by: <git user.name>`, then commit `architecture: <slug>`.
- The plan, the team planner and every developer build within the approved architecture.

## 3. Plan → gate
- Follow the **plan** skill. Do not edit source files in this stage.
- **Gate:** "Accept this plan?" Show files to change, dependencies, order of work, and the riskiest step.
- On Accept: set `Status: accepted` and `Accepted by: <git user.name>`, then commit `plan: <slug>`.

## 3b. Design → gate (UI changes only)
If the change touches anything a user sees, follow the **design** skill now (greenfield sets DESIGN.md, brownfield follows the existing design; impeccable skill; `design/mockup.html`; user approves). Backend-only changes skip this step silently. In team mode the designer agent does this as D-1 on the board instead.

## 4. Build & test (no gate, the toolchain decides)
**Team mode** — if `$ARGUMENTS` contains `--team`, or `.sdlc/config.json` has `team.developers` > 1 and the plan has more than ~3 independent steps: follow the **team** skill instead of the steps below (planner → Epic/Stories/Tasks on the board → developer agents in worktrees → QA agents in the browser → merge into `team/<change>`), then continue with step 5 on that branch. Tell the user the board URL.

- Follow the **build** skill:
  - Dependencies go into the manifest and are installed by `python3 .sdlc/bin/sdlc.py verify` (setup step).
  - Loop on verify until it is green, with at most 5 fix rounds. Fix code, never tests.
  - Keep plan.md in sync.
  - Run the `sdlc:verifier` agent.
- Commit in logical commits.
- If still red after 5 rounds, stop and show the failing output. Ask the user whether to keep trying, change the plan, or stop.
- If a hook blocks something, explain it in one line and adapt. Never work around a hook.

## 5. Review → gate
- Follow the **review** skill: launch the three reviewer agents in parallel, then write review.md.
- Important findings: fix them, re-run verify, re-review. Do this at most twice.
- **Gate:** "Review clean — finish?" Show the tally line and any remaining nits.
- Commit `review: <slug>`.

## 6. Done → next
Show a short summary:
- The branch name, and that it's ready to merge (`git checkout main && git merge <branch>`, or push and open a PR/MR if a remote exists — ask before pushing).
- How to run the app (from CLAUDE.md/plan.md).
- Where the artifacts are (`sdlc/changes/<folder>/`).

Then use AskUserQuestion: "What next?"
- **Add another feature**: ask for it, then go back to step 1 on a new branch from main.
- **Fix a bug**: follow the **bugfix** skill.
- **Stop**

That last question is what makes it a loop: keep going until the user picks Stop.

## Never
- Never push to main.
- Never run production deploys.
- Never edit `.sdlc/config.json`, `.sdlc/state/` or `.sdlc/bin/`.
- Never skip a gate the user owns.
- Never weaken or delete tests to get green.
