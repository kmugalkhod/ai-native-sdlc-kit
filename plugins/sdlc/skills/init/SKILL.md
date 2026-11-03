---
name: init
description: Set up the AI-Native SDLC in the current repo — artifact folders, CLAUDE.md, REVIEW.md, gates config, helper CLI, evals, control bands and CI. Run once per repo.
argument-hint: "[github|gitlab|none]"
disable-model-invocation: true
---
> Windows: where this says `python3`, use `python` (or `py -3`) if `python3` is missing or opens the Microsoft Store.


# /sdlc:init — install the loop into this repo

Arguments: `$ARGUMENTS` — may name the CI flavour (`github` | `gitlab` | `none`) and, for a new project, the stack and commands. CI flavour if not given: `gitlab` when the origin remote contains "gitlab", `github` when it contains "github", else `none`).

## 1. Detect, don't guess
Read the repo before writing anything:
- Setup (dependency install) command: `requirements.txt` → a project virtualenv install, e.g. `python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt` (Windows: `.venv\\Scripts\\pip`); `pyproject.toml` with uv/poetry → `uv sync` / `poetry install`; `package.json` → `npm ci` (or `npm install` if no lockfile); `go.mod` → `go mod download`. When a virtualenv is used, the test/lint commands must use it too (`.venv/bin/pytest -q`).
- New/empty project: there are no files to detect from — take setup/test/lint from the stack the user stated in the arguments, and they become valid once the build stage creates the manifest.
- Build/test/lint commands: Makefile targets, package.json scripts, pyproject/tox/noxfile, go.mod, pom.xml/build.gradle, existing CI files. Prefer ONE command per step that exits non-zero on failure (`make test`, `npm test`, `pytest -q`, `go test ./...`).
- Formatter that can take a single file (`ruff format {file}`, `prettier --write {file}`, `gofmt -w {file}`, `black -q {file}`). Leave empty if unsure.
- Protected paths: generated code, vendored code, frozen packages, migrations (if the team gates them), lockfiles.
- Tracker for the agent team board: `internal` (default), `jira` or `linear` — ask only if the user mentioned Jira/Linear.
- App start command for QA browser testing, with `{port}` (e.g. `.venv/bin/uvicorn app.main:app --port {port}`, `npm run dev -- --port {port}`). Leave empty for non-web projects.
- Team size if the user said one (default 2 developers + 1 QA).

If a verify command cannot be determined, ask the user in ONE question listing what you found. If they are away, leave it empty and say so.

## 2. Scaffold (never overwrites existing files)
Run, with the detected values (quote each value):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/init.py" --root . --ci <ci> \
  --setup "<setup>" --build "<build>" --test "<test>" --lint "<lint>" --format "<format or empty>" \
  --protected <glob> <glob> --tracker <internal|jira|linear> --qa-start "<cmd with {port}>" \
  --developers <n> --qa-agents <n>
```
(Use `python` if `python3` is not on PATH.) The script prints JSON of created and skipped files.

From this moment the gates are live: `.sdlc/config.json`, `.sdlc/state/` and `.sdlc/bin/` are human-owned and the hooks block you from editing them. To change gates later the user edits `.sdlc/config.json` by hand.

## 3. Fill in CLAUDE.md
- If CLAUDE.md was **created**: replace `{Project name}`, `{setup}`, `{build}`, `{test}`, `{lint}` and fill Conventions and Architecture from what you read. Cut to under one page — only what a new joiner needs on day one.
- If CLAUDE.md was **skipped** (exists): do not rewrite it. Append only the missing sections from `${CLAUDE_PLUGIN_ROOT}/templates/CLAUDE.md`: "Verifying your work" and "How work flows here". Keep the user's content intact.
- Same for REVIEW.md: if it existed, leave it.

## 4. Smoke test
- `python3 .sdlc/bin/sdlc.py status` → should say no changes yet.
- `python3 .sdlc/bin/sdlc.py verify` → run it; report which steps pass. A failing baseline is worth knowing before any agent work.
- `python3 .sdlc/bin/monitor.py --dry-run --metric ci_test_failure_rate` (only if PyYAML is installed) → shows the sample band breaching. The sample metric ships `enabled: false`, so the loop ignores it until it points at real data.

## 5. Report (short)
- Created / skipped files.
- Verify baseline result.
- If CI was added: the variables/secrets the user must set (listed at the top of each CI file).
- Next step: `/sdlc:intent <idea>`.
- Suggest committing: `git add -A && git commit -m "chore: adopt AI-native SDLC"` (do not commit unless asked).
