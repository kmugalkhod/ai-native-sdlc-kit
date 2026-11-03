---
name: team
description: Build an accepted change with an agent team — Epic → Stories → Tasks on the board (and Jira/Linear if configured), N developer agents in their own worktrees, M QA agents testing in a real browser, with a live kanban.
argument-hint: "<change> [--developers N] [--qa M] [--simulate]"
disable-model-invocation: true
---

# /sdlc:team — a squad of agents on one change

Arguments: `$ARGUMENTS` (change folder or substring; empty → the single change at stage `build` or `plan-ready` from `python3 .sdlc/bin/sdlc.py status`).

Team size, models, QA start command and tracker come from `.sdlc/config.json` → `team` and `tracker`; `--developers` / `--qa` override the counts for this run. You cannot edit that file (it is human-owned); if something is missing, tell the user the exact key to set.

## 1. Preconditions
- `intent.md` is `Status: accepted`. Prefer an accepted `spec.md` and `plan.md` too: the planner breaks down far better from them. If they are missing, say so and offer `/sdlc:spec` + `/sdlc:plan` first (or continue from the intent if the user wants).
- For browser QA on a web app, `team.qa.start_cmd` should start the app with `{port}` (e.g. `.venv/bin/uvicorn app.main:app --port {port}`). If it is empty, QA tests through the API and test suite only — tell the user once.
- Tracker: `tracker.type` is `internal`, `jira` or `linear`. For Jira the env needs `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` (and `tracker.jira.project_key`); for Linear `LINEAR_API_KEY` (and `tracker.linear.team_key`). If they are missing, the internal board still works — say so.

## 2. Plan the breakdown
```bash
python3 .sdlc/bin/team.py plan <change> [--developers N]
```
The planner agent writes `<change>/breakdown.json` (committed) and loads Epic → Stories → Tasks onto the board with dependencies and a first assignment; with Jira/Linear configured it creates them there too. Show the printed tree.

**Gate** (AskUserQuestion): "Start the team on this breakdown?" — Accept (Recommended) / Change something / Stop.
On *Change something*: ask what to change and edit `breakdown.json` together. The board already holds the old plan and only a human can wipe it, so ask the user to run `python3 .sdlc/bin/team.py reset` in their own terminal, then re-run `plan`.

## 3. Start the board and the team (both in the background)
```bash
python3 .sdlc/bin/board_server.py            # run_in_background: true → prints http://127.0.0.1:<port>
python3 .sdlc/bin/team.py run <change> [--developers N] [--qa M]   # run_in_background: true
```
Tell the user the board URL in one line. They can watch the kanban live, search everything, open any task's history, and message any agent from the page.

## 3b. Design gate (only when the change has UI)
The breakdown adds a **D-1 Design** item when any task changes what users see (`team.design.mode`: auto/always/never). A designer agent (impeccable skill; greenfield sets DESIGN.md, brownfield follows it) produces `<change>/design/mockup.html` in its own worktree while backend tasks continue. UI tasks wait until the human approves.
When D-1 reaches *Needs approval* (wait for it with a background `until python3 .sdlc/bin/board.py task D-1 | grep -q '"status": "review"'; do sleep 10; done`):
1. Tell the user the board shows the design, give the mockup link (`http://127.0.0.1:<board port>/design/D-1`) and, if you can, a screenshot.
2. AskUserQuestion: "Approve design D-1?" — **Approve (Recommended)** / **Request changes** / **Stop**.
3. Approve → `python3 .sdlc/bin/board.py design-approve D-1 "<their note>"`. Changes → ask what, then `python3 .sdlc/bin/board.py design-changes D-1 "<their words>"`; the designer revises and it comes back. You run these only after the user chose — never decide for them.
The user can also click Approve / Request changes on the board page.
For the impeccable skill: `/plugin marketplace add pbakaus/impeccable` then `/plugin install impeccable@impeccable` (or list a local plugin folder in `team.design.plugin_dirs`).

## 4. While it runs
Do not poll in a loop. When the user asks, or when the run finishes, run `python3 .sdlc/bin/team.py status` and summarise in a few lines: tasks done/total, who is on what, QA bounces, escalations waiting for a human (and what they need).

## 5. When it finishes
- Exit 0: everything merged into `team/<change>`, integration verify ran, `team-report.md` committed. Offer `/sdlc:review <change>` on that branch, then a PR/MR (ask before pushing).
- Exit 3: some tasks escalated. List each with its reason from the board and ask the user for guidance (AskUserQuestion). Once they answer, the **user** runs `python3 .sdlc/bin/board.py resume <T-n> "<guidance>"` (or clicks **Resume with guidance** on the task in the board page) — agents cannot resume; then re-run `team.py run <change>` — it resumes where it stopped.

## Never
Push to main, edit `.sdlc/config.json`, or run `team.py reset` yourself.
