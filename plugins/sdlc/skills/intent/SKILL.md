---
name: intent
description: Stage 1 Plan — brainstorm an idea, ticket or incident with the originator and capture it as a committed intent.md (problem, outcome, users/systems, constraints, open questions).
argument-hint: "<idea, ticket id/URL, or slug> [--headless]"
disable-model-invocation: true
---

# /sdlc:intent — capture intent once, in the originator's words

Input: `$ARGUMENTS`

You are playing the analyst. The output is `sdlc/changes/<date>-<slug>/intent.md` that the product owner accepts or rejects. Read `.sdlc/config.json` for `changes_dir` and `tracker` if the repo is initialised; if `.sdlc/` is missing, tell the user to run `/sdlc:init` first and stop.

## 1. Source the idea
- Free text → that is the idea.
- A ticket id/URL (Jira key, GitLab/GitHub issue) → if a connector/CLI can read it (`gh issue view`, `glab issue view`, a Jira MCP tool), read it; record the id in the `Record:` field. That system stays the record of truth; intent.md links to it.
- An existing change slug → open its intent.md and continue refining it.

## 2. Brainstorm until concrete (interactive)
Ask the questions an analyst would, a few at a time, in plain language — no formal requirements language:
- What can't people do today? Who is affected, how often, what does it cost? Any evidence?
- What does better look like, seen from the outside?
- Which users and systems are touched?
- Constraints: data/PII, security, policy, budget, deadline, tech that must or must not be used.
- What is explicitly out of scope?
- How will we know it worked (metric + target)?
Read the codebase quietly to ground the conversation (which systems exist, what is already there), but do not design the solution here.

With `--headless`: ask nothing. Use the input plus what the code shows; put every assumption in **Open questions** prefixed `ASSUMED:`.

## 3. Write it
- New change: `python3 .sdlc/bin/sdlc.py new <slug> --title "<title>"` creates the folder from the org template and prints its path. Fill every section of that intent.md in the originator's terms. Keep it to about a page.
- Status stays `draft`. Never set `accepted` yourself — that is the product owner's decision.
- Show the user the file and ask them to correct anything you misunderstood. Apply corrections.

## 4. Commit (only when the user agrees)
```bash
git add <change>/intent.md && git commit -m "intent: <slug>" -m "Record: <id or none>"
```
Author + timestamp in git is the evidence. Tell the user: the product owner sets `Status: accepted` (or `rejected`) and merges; acceptance is what triggers `/sdlc:spec` (or the CI loop).
