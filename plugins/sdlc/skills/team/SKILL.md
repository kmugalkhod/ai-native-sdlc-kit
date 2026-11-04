---
name: team
description: Build an accepted change with an agent team — this session is the team lead and runs persistent developer, QA and designer teammates (Claude Code Agent Teams), each in its own git worktree, one story per assignment, with the live board, design approval and Jira/Linear sync.
argument-hint: "<change> [--developers N] [--qa M] [--background]"
disable-model-invocation: true
---
> Windows: where this says `python3`, use `python` (or `py -3`) if `python3` is missing or opens the Microsoft Store.

# /sdlc:team — you are the team lead

Arguments: `$ARGUMENTS` (change folder or substring; empty → the single change at stage `build` or `plan-ready` from
`python3 .sdlc/bin/sdlc.py status`). Team size, models, QA start command and tracker come from `.sdlc/config.json`
(`team`, `tracker`); `--developers` / `--qa` override the counts. You cannot edit that file; if a key is missing, tell
the user the exact key.

**Division of labour.** `team.py` does all bookkeeping deterministically in seconds: worktrees, branches, installs,
story batches, QA groups, merges, the board, the design gate, crash recovery. You only relay its assignments to your
teammates and bring the human in when it says so. Never do teammates' work yourself, never run git merges, never
decide for the human.

## 0. Mode
Run `python3 -c "import os;print(os.environ.get('CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS',''))"`.
- `1` → Agent Teams mode (below). This is the fast mode.
- anything else, or `--background` in the arguments → tell the user in two lines that Agent Teams is off and give the
  setting to enable it (`"env": {"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"}` in `~/.claude/settings.json`, then
  restart Claude Code). If they want to go on without it, use **Background mode** at the end.

## 1. Preconditions
- `intent.md` is `Status: accepted`; prefer accepted `spec.md` + `plan.md`. Missing → offer `/sdlc:spec` / `/sdlc:plan`.
- `team.qa.start_cmd` starts the app with `{port}` for browser QA; empty → QA uses tests and API calls (say so once).

## 2. Plan
```bash
python3 .sdlc/bin/team.py plan <change> [--developers N]
```
Show the tree it prints (stories, tasks, who, what waits for the design). Gate with AskUserQuestion: "Start the team
on this breakdown?" — **Start (Recommended)** / **Change something** / **Stop**. On a change: edit
`<change>/breakdown.json` with the user, then run `plan` again (it reloads while no work has started).

## 3. Permissions (once per project)
Teammates' permission prompts all land in this window and stall the team. Ask with AskUserQuestion: "Pre-approve the
commands teammates need (git, python, npm, tests, file edits) for this project? `git push` stays blocked." —
**Pre-approve (Recommended)** / **Ask me each time**. On yes: `python3 .sdlc/bin/team.py allow`, then tell the user to
restart Claude Code only if it says the rules did not load.

## 4. Start
```bash
python3 .sdlc/bin/board_server.py        # run_in_background: true → board URL
python3 .sdlc/bin/team.py prepare <change> [--developers N] [--qa M]    # timeout 600000
```
`prepare` creates the worktrees, installs dependencies in all of them in parallel, recovers anything a previous
session left behind, and prints JSON: `assignments`, `waiting_for_human`, `working`, `progress`, `finished`, `board`.
Tell the user the board URL in one line.

## 5. The loop
For every entry in `assignments`:
- `"action": "spawn"` → spawn a teammate with the Agent tool: `name` = the entry's `agent` (exactly), `subagent_type`
  = `agent_type`, `model` = `model`, prompt = the entry's `message`. Spawn all of them in ONE message so they start
  together.
- `"action": "send"` → SendMessage to that teammate with the entry's `message`.
The message only points at an assignment file; never paste or rewrite its content.

Then wait. Do not poll. Teammates message you `done <keys>: …` or go idle. Each time one does, run
```bash
python3 .sdlc/bin/team.py next <change> --done <that teammate's name>      # timeout 600000
```
(name several with `--done a b` if several finished). Relay the new assignments the same way. Keep going until
`finished` is true.

**Keep the user informed** — after every step write ONE line, so they always see something happening, e.g.
`✓ T-2 passed QA and merged · dev-1 started T-3, T-4, T-5 · qa-1 testing T-12 · 4/18 done`
(what finished, what merged, who started what, `progress`). Never go silent for a step.

**Time checks without polling.** Right after relaying assignments, start (or keep) one background watcher:
```bash
python3 .sdlc/bin/team.py watch <change>      # run_in_background: true
```
It exits when handed-in work is waiting for an idle QA teammate (`work_waiting` → run `next <change>` without
`--done` and relay), or when a teammate is past its time budget (from `.sdlc/config.json`: `team.run_timeout_minutes` for developers,
`team.qa.minutes_per_task` × tasks for QA), or after 30 minutes with an empty list. For each `over_budget` entry,
SendMessage that teammate the entry's `message` — a time check, not a stop: it never cancels work. Then start the
watcher again. Tell the user in one line (`⏱ qa-1 is 12 min into T-12 (budget 4) — asked for a status`). If a teammate
is still silent long after that, look at its transcript; if it is truly stuck, ask it to shut down and run
`next --done <name>` — its committed work is kept and the next assignment continues from it.

## 6. The human, only when `waiting_for_human` says so
- **Design approval** (`what: design approval`): give the user the `mockup` link, then AskUserQuestion "Approve the
  design?" — **Approve (Recommended)** / **Request changes** / **Stop**. Approve → `python3 .sdlc/bin/board.py
  design-approve D-1 "<their note>"`; changes → ask what, then `python3 .sdlc/bin/board.py design-changes D-1
  "<their words>"`. Then `next`. Run these only after the user chose. Backend work never waits for this.
- **Escalated** (`what: escalated`): show the reason, ask the user for guidance; the **user** resumes it
  (`python3 .sdlc/bin/board.py resume <key> "<guidance>"` in their terminal, or *Resume with guidance* on the board).
  Then `next`.

## 7. Finish
When `finished` is true:
```bash
python3 .sdlc/bin/team.py wrap <change>
```
It runs the full verify on the team branch and commits `team-report.md`. Ask every teammate to shut down. Report in a
few lines: tasks done, QA bounces, the branch `team/<change>`, and offer `/sdlc:review <change>`, then a PR (ask before
pushing).

## Restarting
A new Claude Code session has no teammates. Run `prepare` again: it marks the old session's open work as interrupted,
keeps every commit, releases stale QA claims, and hands out fresh assignments that continue the work (all `spawn`).

## Background mode (Agent Teams off)
```bash
python3 .sdlc/bin/board_server.py                          # run_in_background: true
python3 .sdlc/bin/team.py run <change> [--developers N] [--qa M]   # run_in_background: true
```
Separate headless agents per task — slower. For status questions run only `python3 .sdlc/bin/team.py status`; never
search for ports or processes. Design approval and escalations work as in step 6, then re-run `team.py run`.

## Never
Push to main, edit `.sdlc/config.json`, run `team.py reset`, merge branches yourself, or approve a design or resume a
task without the human choosing it.
