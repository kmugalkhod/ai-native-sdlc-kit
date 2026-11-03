# {Project name}

<!-- Keep this under a page. When Claude makes the same mistake twice, the correction goes here. -->

## Commands
- Setup (install deps): `{setup}`
- Build: `{build}`
- Test: `{test}`
- Lint: `{lint}`

## Verifying your work
- Run `python .sdlc/bin/sdlc.py verify` (setup → build → test → lint) before reporting any task complete, and paste the output.
- New dependency: add it to the manifest (requirements.txt / pyproject.toml / package.json) with a version constraint, then run verify — the setup step installs it. Never pip/npm install ad hoc.
- If a test fails, fix the code, not the test. Never skip, delete or loosen a failing test.
- For bug fixes: reproduce the bug as a failing test first (`/sdlc:bugfix`).

## Conventions
<!-- Language/framework versions, patterns that matter, naming. -->

## Architecture
<!-- Top-level folders and what lives where. Generated code you must never edit. -->

## How work flows here (AI-native SDLC)
- Every change lives in `sdlc/changes/<date>-<slug>/`: intent.md -> spec.md -> plan.md -> code + tests -> review.md.
- Nothing is implemented without an accepted plan.md. When the implementation departs from the plan, update plan.md in the same commit.
- Governance files (`.sdlc/config.json`, `.sdlc/state/`, `.sdlc/bin/`) are human-owned; hooks block edits to them.
- The agent never pushes to a protected branch and never runs a production action without a release authorization.

## Things Claude gets wrong
<!-- One line per repeated mistake. -->
