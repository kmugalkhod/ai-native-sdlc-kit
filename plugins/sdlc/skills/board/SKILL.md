---
name: board
description: Open the live team board — kanban of tasks, epic/story/task tree, search, agent status and team chat — for the change the agent team is working on.
argument-hint: "[--port N]"
disable-model-invocation: true
---

# /sdlc:board

Start the board server in the background (Bash `run_in_background: true`), passing `$ARGUMENTS` through:
```bash
python3 .sdlc/bin/board_server.py $ARGUMENTS
```
It prints `team board: http://127.0.0.1:<port>`. Reply with that URL in one line, then one line of state from `python3 .sdlc/bin/team.py status` (change, tasks done/total, agents working).

If the board is empty, say so and point to `/sdlc:team <change>`.
The page binds to localhost and has no login; do not expose it on another interface unless the user asks.
