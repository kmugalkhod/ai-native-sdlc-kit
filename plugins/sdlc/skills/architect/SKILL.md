---
name: architect
description: Design or update the system architecture for an accepted spec before it is planned — sdlc/ARCHITECTURE.md with a Mermaid diagram, decision records (ADRs), and SVG/PNG/draw.io exports — for human approval. Runs for new projects and for changes that add a component, data store, queue, external service or deployment unit; skipped otherwise.
argument-hint: "<change folder or substring>"
disable-model-invocation: true
---
> Windows: where this says `python3`, use `python` (or `py -3`) if `python3` is missing or opens the Microsoft Store.

# /sdlc:architect — decide how it is built, once, before planning

Change: `$ARGUMENTS`. Resolve it to one folder under `sdlc/changes/`. If none is given, use the change whose spec was
accepted most recently.

## When it runs
- **Always:**
  - when the repo has no `sdlc/ARCHITECTURE.md` and the change is a new product or a sizeable feature (more than
    about 5 files, or more than one component)
  - when the user asks
- **Only if needed:** when `ARCHITECTURE.md` exists, run it only if the spec adds or changes a component, data store,
  queue, external service, public API surface, auth model or deployment unit.
  - Small changes skip silently. Say one line: "architecture unchanged".

## Do
1. **Precondition:** `spec.md` is `Status: accepted`.
2. **Launch the `sdlc:architect` agent** with the change folder.
   - If it replies `NO ARCHITECTURE CHANGE`, say so in one line and stop.
3. **Check what it wrote:**
   - `sdlc/ARCHITECTURE.md` is `Status: proposed`.
   - Every ADR it links exists.
   - `sdlc/architecture.drawio` exists. If it is missing, run `python3 .sdlc/bin/arch_export.py` yourself.
4. **Resolve the open questions:** for every `- [ ]` open question, ask the user with AskUserQuestion, using the
   options it lists. Record each answer as `- [x] … — decided by <user>`, and update the ADR it affects.

## Gate (always the user's call; never auto-approved, not even with `--auto`)
Use AskUserQuestion: "Approve this architecture?" with these options:
- **Approve (Recommended)**
- **Change something**
- **Stop here**

Put in the question:
- the design's shape in 3–5 lines
- the 2–3 key decisions
- where to look: `sdlc/architecture.png` or `.svg` (the picture), `sdlc/ARCHITECTURE.md` (the text), plus
  `sdlc/architecture.drawio` (open it in diagrams.net or the draw.io VS Code extension to move things around)

On **Approve**:
1. Set `Status: approved`, `Approved by: <git user.name>` and `Approved for: <change folder>` in
   `ARCHITECTURE.md`, and set the new ADRs to `Status: accepted`.
2. Commit `architecture: <slug>`.

On **Change something**:
1. Ask what to change.
2. Re-launch the architect with that feedback.
3. Ask the gate again.

## After approval
Nothing is planned against an unapproved architecture. The pipeline escalates and `team.py prepare` refuses while
`ARCHITECTURE.md` is `Status: proposed`. Planner and developer agents read the approved file. The gatekeeper and the
compliance reviewer flag a plan or diff that adds a component the architecture does not have. The fix is either a new
architecture change approved by a human, or changing the code back.
