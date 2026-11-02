---
name: babysit
description: Stage 5 Deploy — take an open PR/MR to green: sweep unresolved review comments and failing checks, fix and push, repeat until it waits only on code-owner approval.
argument-hint: "[PR/MR number or URL] [--rounds N]"
disable-model-invocation: true
---

# /sdlc:babysit — address review comments and failing checks until green

Target: `$ARGUMENTS` (empty → the PR/MR for the current branch). Max rounds: `--rounds`, default 3.

Use `gh` for GitHub and `glab` for GitLab (pick by `git remote get-url origin` or `.sdlc/config.json` vcs). If neither CLI is authenticated, say so and stop.

## Each round
1. **Collect**
   - GitHub: `gh pr view <n> --json number,headRefName,reviewDecision,statusCheckRollup`, `gh pr checks <n>`, unresolved review threads via `gh api graphql` (reviewThreads where isResolved=false) and PR comments mentioning `@claude`.
   - GitLab: `glab mr view <n> --comments`, `glab ci status`, `glab ci view` / job logs for failures.
2. **Triage** each item: actionable code change / question to answer / disagreement to escalate. Never "fix" a comment by weakening a test, deleting a check, or editing governance files.
3. **Fix** actionable items on the PR branch. Failing check → read the log, reproduce locally, fix, run `python3 .sdlc/bin/sdlc.py verify`. Departures from plan.md → update plan.md in the same commit.
4. **Push** the branch (never a protected branch) and reply on each thread with what changed and the commit sha. Resolve only threads you fully addressed.
5. **Stop** when checks are green and no actionable threads remain, when only code-owner approval is pending, or after max rounds. Report the state and any items you escalated to a human.

You do not merge. Approval and merge belong to the code owner through branch protection.
