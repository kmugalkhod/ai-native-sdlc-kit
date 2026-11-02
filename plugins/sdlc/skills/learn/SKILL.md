---
name: learn
description: Turn a repeated mistake or review finding into a one-line CLAUDE.md rule (or a skill/hook when it must always hold), keeping CLAUDE.md under a page.
argument-hint: "<the mistake or correction>"
disable-model-invocation: true
---

# /sdlc:learn — when Claude makes a mistake twice, the correction goes into CLAUDE.md

Mistake/correction: `$ARGUMENTS` (empty → use the most recent correction the user gave in this session).

1. Decide where it belongs:
   - A convention, command or gotcha for this repo → **CLAUDE.md** ("Things Claude gets wrong" or the matching section).
   - Institutional policy that must apply consistently across repos → a **skill** (`.claude/skills/<name>/SKILL.md`, owned by the policy owner).
   - Must hold without exception → a **hook** or `protected_paths`/`test_globs` entry in `.sdlc/config.json` — you cannot edit that file; draft the exact change and ask a human to apply it.
2. For CLAUDE.md: write one imperative line, specific enough to act on ("Money is BigDecimal, never double" — not "be careful with money"). Merge with an existing line if it overlaps. If CLAUDE.md is longer than about a page, propose cutting stale lines in the same edit.
3. Show the diff. Commit only if the user agrees: `git commit -m "docs(claude.md): <rule>"` — code owners review it like code, and CI re-runs the evals because CLAUDE.md changed.
