---
name: review
description: Stage 5 Deploy — run the REVIEW.md passes (bugs, security, compliance against spec.md and plan.md) on the current branch's diff with parallel reviewer agents, and write severity-ranked findings to review.md.
argument-hint: "[change folder or substring] [--base <ref>] [--headless]"
disable-model-invocation: true
---

# /sdlc:review — identical passes on every change, humans judge intent and risk

Arguments: `$ARGUMENTS`

## Scope
- Base ref: `--base` if given, else the merge-base with the default branch (`git merge-base HEAD origin/main` or `master`).
- Diff: `git diff <base>...HEAD` plus uncommitted changes.
- Change folder: the argument, else infer from branch name `sdlc/<folder>` or from files under `sdlc/changes/` in the diff. Without one, the compliance pass checks CLAUDE.md and design principles only.

## Run the passes in parallel
Launch these agents in ONE message so they run concurrently, each given the base ref, the change folder path and REVIEW.md:
- `sdlc:bug-reviewer`
- `sdlc:security-reviewer`
- `sdlc:compliance-reviewer`

## Consolidate
1. De-duplicate; when two passes report the same issue keep one, tagged with both.
2. Re-check every **Important** finding yourself against the code — drop false positives, and say so in a note.
3. Apply REVIEW.md: its definition of Important, the nit cap, the do-not-report list.
4. Write `review.md` in the change folder from `.sdlc/templates/review.md` (or print it if there is no change folder). The **Tally** line format is exact: `Important: <n> · Nit: <n> · Pre-existing: <n>` — automation reads it.
5. **CLAUDE.md updates**: if a finding repeats a mistake seen before (check `git log -p CLAUDE.md` and earlier review.md files), propose the CLAUDE.md line. Flag CLAUDE.md content this diff made stale.

Findings never approve or block a merge on their own; branch protection and a code owner decide.

## Next
- Important > 0: offer to fix them (fix code, never weaken tests; update plan.md for deviations), then re-run `/sdlc:review`.
- Clean: push the branch and open a PR/MR; then `/sdlc:babysit` takes it to green.
