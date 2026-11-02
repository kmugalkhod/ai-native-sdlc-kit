# AI-Native SDLC for Claude Code

A Claude Code plugin (`sdlc`) that runs Anthropic's *AI-Native SDLC Playbook* end to end:
**Plan → Design → Build → Test → Deploy → Maintain**, as a loop. Every stage commits an artifact the
next stage reads; skills carry policy; hooks are the deterministic gates; evals regression-test the
agent's config; control bands close the loop by writing the next `intent.md`.

## Install

```bash
# from a clone of this repo (local)
claude plugin marketplace add /path/to/ai-native-sdlc-kit
claude plugin install sdlc@ai-native-sdlc

# or from your Git host
claude plugin marketplace add <owner>/<repo>          # GitHub
claude plugin marketplace add https://gitlab.example.com/tools/ai-native-sdlc.git
claude plugin install sdlc@ai-native-sdlc
```
Try without installing: `claude --plugin-dir ./plugins/sdlc`.
Needs Python 3.8+ (`python3` or `python`), git; PyYAML only for the monitor; `gh`/`glab` only for PR steps.

## Quick start (in your app repo)

```text
/sdlc:init gitlab            # scaffold: sdlc/changes, CLAUDE.md, REVIEW.md, .sdlc/ gates + CLI, evals, bands, CI
/sdlc:intent customers can't see claim status in the portal
                             # PO sets Status: accepted in intent.md, commits
/sdlc:spec claim-status      # requirements+design, policy skills applied, concerns flagged
                             # PO resolves concerns, sets Status: accepted
/sdlc:plan claim-status      # plan mode: files, order, tests, risks → plan.md; engineer accepts
/sdlc:build claim-status     # implement + verify until green; plan.md kept in sync; verifier agent
/sdlc:review claim-status    # 3 parallel passes (bugs/security/compliance) → review.md
/sdlc:babysit                # take the PR/MR to green; code owner approves + merges
/sdlc:status --metrics       # where every change is + playbook indicators from git
```
Also: `/sdlc:bugfix` (failing-test-first + test lock), `/sdlc:triage` (incident → intent.md),
`/sdlc:learn` (repeat mistake → CLAUDE.md), `/sdlc:evals run|add`.

## Playbook → kit

| Stage / play | Kit |
|---|---|
| 1 Plan · capture intent.md | `/sdlc:intent`, `.sdlc/templates/intent.md`, `sdlc.py new` |
| 2 Design · requirements & design | `/sdlc:spec` — loads every relevant policy skill, `- [ ]` flagged concerns |
| 3 Build · plan mode | `/sdlc:plan` → `plan.md` (no source edits until accepted) |
| 3 Build · auto mode / CLAUDE.md / skills | `/sdlc:build`, CLAUDE.md template, `/sdlc:learn`, `sdlc-artifacts` skill, `examples/skills/api-security` |
| 3 Build · hooks as guardrails | protected paths, secret scan, formatter/lint-on-edit, governance files locked |
| 3 Build · parallel sessions & subagents | `claude --worktree <name>` per task; agents `researcher`, `verifier`, `simplifier` |
| 4 Test · feedback loop | `sdlc.py verify`, CLAUDE.md "Verifying your work", `/sdlc:bugfix` + **fix mode** (test edits blocked) |
| 4 Test · continuous evals | `evals.py` (worktree per case, tests *uncommitted* config), `agent-evals.yml` / GitLab `sdlc:evals` |
| 5 Deploy · AI in PR review | `/sdlc:review` (3 reviewer agents), `REVIEW.md`, `claude-review.yml` (+ `@claude` fixes), GitLab `sdlc:review`, `/sdlc:babysit` |
| 5 Deploy · hooks as approval gates | production gate (needs `approve-release` by a human), no push to protected branches, audit log |
| 5 Deploy · CI/CD | `pipeline.py`, `sdlc-loop.yml`, GitLab `sdlc:loop`; `examples/managed-settings.json` |
| 6 Maintain · closing the loop | `monitor.py` + `bands.yaml` (Western Electric rules, tiers log/diagnose/propose, cooldown) → `/sdlc:triage` → intent.md |
| 6 Maintain · gates between stages | `gatekeeper` agent + deterministic checks; `ESCALATION.md` hands off to a human |
| Measure | `sdlc.py metrics`: intent→spec h, spec→plan h, rework after plan, survival rate |

## Governance model

- **Human-owned files**: `.sdlc/config.json`, `.sdlc/state/`, `.sdlc/bin/`, `.sdlc/audit.jsonl` — hooks block the agent from editing them (Edit/Write *and* shell). `protected_paths` default also covers `.claude/settings.json` and `REVIEW.md`.
- **Human-only actions** need an interactive terminal (the agent's Bash tool can't do them):
  - `python3 .sdlc/bin/sdlc.py fix-mode off`
  - `python3 .sdlc/bin/sdlc.py approve-release CHG-1234` (TTL from config; or launch with `RELEASE_APPROVAL=...`)
- **Production gate**: commands matching `prod_gate.patterns` are blocked without an approval (`mode: "ask"` prompts instead).
- **No direct push** to `protected_branches`; everything arrives as a PR/MR.
- **Audit**: every block/ask/allow-with-approval, gate verdict, fix-mode and release event → `.sdlc/audit.jsonl` (local; git history is the durable trail).
- All hooks are no-ops in repos without `.sdlc/config.json`, so installing the plugin globally is safe.

## Headless loop

```bash
python3 .sdlc/bin/pipeline.py claim-status --to plan          # spec → gate → plan → gate, commits on sdlc/<change>
python3 .sdlc/bin/pipeline.py claim-status --from build --pr  # build → verify/fix ×3 → review/fix → PR/MR
python3 .sdlc/bin/pipeline.py claim-status --dry-run
python3 .sdlc/bin/monitor.py --dry-run                         # sample band breaches on first run
python3 .sdlc/bin/evals.py --case verify-before-done
```
Exit code 3 = escalated (see `ESCALATION.md`). The intent must already be accepted by a human; nothing passes the production gate.

## Models / Bedrock

Per-stage models live in `.sdlc/config.json → models` (defaults `sonnet`; researcher agent `haiku`). Works with Sonnet + Haiku only. For Bedrock set `CLAUDE_CODE_USE_BEDROCK=1` and `AWS_REGION` (CI files have the commented block). Add `opus` per stage when available — config only, no code change.

## Layout

```
.claude-plugin/marketplace.json
plugins/sdlc/
  .claude-plugin/plugin.json
  skills/      init intent spec plan build bugfix review babysit triage status learn evals sdlc-artifacts
  agents/      researcher verifier simplifier bug-reviewer security-reviewer compliance-reviewer gatekeeper
  hooks/       hooks.json run.sh
  scripts/     sdlc_core.py sdlc_hooks.py sdlc.py pipeline.py evals.py monitor.py init.py
  templates/   CLAUDE.md REVIEW.md .sdlc/ sdlc/ evals/ .claude/ .github/ .gitlab/ examples/
```

Windows: hooks run through `bash` (Git Bash) and find `python3` or `python`.
