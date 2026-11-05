---
name: spec
description: Stage 2 Design — turn an accepted intent.md into a requirements-and-design spec.md in one pass, applying the org's policy skills and flagging every area of concern for the product owner.
argument-hint: "<change folder or substring> [--headless]"
disable-model-invocation: true
---
> Windows: where this says `python3`, use `python` (or `py -3`) if `python3` is missing or opens the Microsoft Store.


# /sdlc:spec — requirements and design in one session

Change: `$ARGUMENTS` (resolve to one folder under `sdlc/changes/`; if empty or ambiguous, run `python3 .sdlc/bin/sdlc.py status` and pick the single `design-ready` change, or ask).


> If `sdlc/MISSION.md` is filled in, read it first. When the intent asks for something its **Never** list rules out,
> say so in the spec's flagged concerns (`- [ ]`) instead of specifying it — a human decides.

## Preconditions
- `intent.md` must be `Status: accepted`. If not, stop and say the product owner has to accept it first.
- If `spec.md` already exists, revise it rather than starting over, and keep resolved concerns.

## Do
1. Read intent.md, CLAUDE.md, and the parts of the codebase the change touches (use the `sdlc:researcher` agent for wide sweeps so your context stays on the spec).
2. Discover the policies in force: list the skills available to you (project `.claude/skills/`, plugins). Load every one relevant to this change — brand, security, API, privacy/compliance, UX, accessibility, data. Apply them as constraints while writing, not as an afterthought.
3. Write `spec.md` in the change folder from `.sdlc/templates/spec.md` (fallback `${CLAUDE_PLUGIN_ROOT}/templates/.sdlc/templates/spec.md`):
   - Header: `From: intent.md (<short sha of last intent commit>)`, `Status: draft`, `Skills applied:` with each skill name.
   - Numbered, testable functional requirements; NFRs; design (components, data/interfaces, UX); Given/When/Then acceptance criteria that each map to an FR.
   - Answer every open question from intent.md or carry it forward with an owner.
   - **Flagged concerns**: one `- [ ]` line per concern that genuinely needs a decision — two policies contradict, the intent conflicts with a policy, or the change makes a risky call (auth, PII, data, public API). Name the policy and the owner. An analyst would have escalated these; the product owner resolves them with the policy owner before engineering sees the spec.
   - Assumptions that a reasonable engineer would make and a reviewer should merely see go as `- [~] ASSUMED: ... — why`. They do not block. Do not inflate assumptions into concerns, and do not hide real conflicts as assumptions.
4. For front-end work, describe screens and states precisely enough to mock; if a mock exists, link it.

## Gate (interactive)
Walk the product owner through the flagged concerns first. As each is resolved, change it to `- [x]` with the decision and who made it. The spec is ready when there are no `[ ]` concerns. Only the product owner (with a tech lead for higher-risk changes) sets `Status: accepted`. Accepting the spec is what starts `/sdlc:plan`.

With `--headless`: do not ask. Real concerns stay `[ ]` — the headless loop escalates them to a human; assumptions go as `[~]` and the gatekeeper judges them.

## Commit (when the user agrees)
`git add <change>/spec.md && git commit -m "spec: <slug>"` — intent.md + spec.md together record what was asked for and what was decided.
