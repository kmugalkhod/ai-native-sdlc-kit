#!/usr/bin/env python3
"""The agent team: break an accepted change into Epic → Stories → Tasks, then run a team of developer and
QA agents on it like a real squad.

  python .sdlc/bin/team.py plan <change>                  planner agent writes breakdown.json → board (+ Jira/Linear)
  python .sdlc/bin/team.py run <change> [--developers 2] [--qa 1] [--pr] [--simulate]
  python .sdlc/bin/team.py status
  python .sdlc/bin/team.py reset                          wipe the board (human, terminal only)

How a run works
  • The lead (this script) owns the board and never writes code. It assigns tasks, respects dependencies, keeps
    two developers off the same files, and mirrors everything into Jira/Linear when configured (hybrid sync).
  • Every developer agent has its own git worktree (.sdlc/worktrees/dev-N) and a branch per task
    (team/<change>/T-3). It implements, runs verify until green, commits, and runs `board.py submit`.
  • A QA agent takes the hand-off in its own worktree, starts the app (team.qa.start_cmd), tests every acceptance
    criterion in a real browser (Playwright MCP) and through the API, adds automated tests, then `qa-pass` or
    `qa-fail` with a bug report. A failed task goes straight back to its developer with the report.
  • Agents talk through the board: `board.py ask/reply/inbox`. A developer who runs `board.py blocked` gets an
    idle teammate sent to read their worktree and answer; after max_help_rounds the task escalates to a human.
  • QA-passed work is merged into the integration branch team/<change>. A merge conflict goes back to the developer.
    The lead never pushes to main; --pr pushes the integration branch and opens a PR/MR for a human.
Everything is visible live in the board page: python .sdlc/bin/board_server.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import functools
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from board import Board, STATUS_LABEL  # noqa: E402
from sdlc_core import audit, changes, find_root, git, header_field, load_config, matches_any, utcnow  # noqa: E402
import trackers  # noqa: E402

BOARD_CLI = "python3 .sdlc/bin/board.py"
BASE_TOOLS = ["Read", "Grep", "Glob"]
EDIT_TOOLS = ["Edit", "Write", "MultiEdit"]
SAFE_BASH = ["Bash(python3 .sdlc/bin/*)", "Bash(python .sdlc/bin/*)", "Bash(git status*)", "Bash(git diff*)",
             "Bash(git log*)", "Bash(git show*)", "Bash(git add *)", "Bash(git commit *)", "Bash(ls*)",
             "Bash(cat *)", "Bash(mkdir *)", "Bash(pwd)"]
DEV_BASH = ["Bash(git merge *)", "Bash(git checkout -- *)", "Bash(.venv/bin/*)", "Bash(python3 -m pytest*)", "Bash(python -m pytest*)", "Bash(.venv/Scripts/*)",
            "Bash(npm *)", "Bash(npx *)", "Bash(node *)"]
QA_BASH = ["Bash(curl *)", "Bash(.venv/bin/*)", "Bash(python3 -m pytest*)", "Bash(python -m pytest*)", "Bash(.venv/Scripts/*)", "Bash(npx playwright*)"]


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def sh(cmd, cwd, timeout=600, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True, text=True,
                          timeout=timeout, env=env)


def resolve_change(root: Path, cfg: dict, name: str) -> Path:
    hits = [c for c in changes(root, cfg) if name in c.name]
    if len(hits) != 1:
        sys.exit(f"change '{name}' matched {len(hits)} folders: {[h.name for h in hits]}")
    return hits[0]


def extract_json(text: str) -> dict | None:
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S) or re.search(r"(\{.*\})", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


# ====================================================================== claude runner
class AgentRun:
    """One headless Claude session. Streams tool use into the board so the kanban shows live activity."""

    def __init__(self, board: Board, name: str, cwd: Path, prompt: str, model: str, tools: list[str],
                 item_key: str | None, timeout_min: int, mcp: dict | None = None, extra_env: dict | None = None,
                 add_dirs: list[str] | None = None, plugin_dir: str | list | None = None):
        self.b, self.name, self.cwd, self.item_key = board, name, cwd, item_key
        self.cmd = ["claude", "-p", prompt, "--model", model, "--output-format", "stream-json", "--verbose",
                    "--permission-mode", "acceptEdits", "--allowedTools", *tools,
                    "--disallowedTools", "Bash(git push*)"]
        if mcp:
            mcp_file = Path(board.path).parent / f"mcp-{name}.json"
            mcp_file.write_text(json.dumps({"mcpServers": mcp}, indent=2), encoding="utf-8")
            self.cmd += ["--mcp-config", str(mcp_file)]
        for d in add_dirs or []:
            self.cmd += ["--add-dir", d]
        for d in ([plugin_dir] if isinstance(plugin_dir, str) else (plugin_dir or [])):
            if d:
                self.cmd += ["--plugin-dir", d]
        self.env = {**os.environ, **(extra_env or {})}
        self.timeout = timeout_min * 60
        self.proc: subprocess.Popen | None = None
        self.result_text, self.cost, self.error = "", 0.0, None

    def describe(self, block: dict) -> str | None:
        n, i = block.get("name", ""), block.get("input") or {}
        if n in ("Edit", "Write", "MultiEdit"):
            return f"{n.lower()} {i.get('file_path', '').split('/worktrees/')[-1].split('/', 1)[-1]}"
        if n == "Bash":
            c = (i.get("command") or "").replace("\n", " ")
            return f"$ {c[:110]}"
        if n.startswith("mcp__playwright__"):
            what = i.get("url") or i.get("element") or i.get("text") or ""
            return f"browser: {n.split('__')[-1].replace('browser_', '')} {str(what)[:80]}".strip()
        if n == "Skill":
            return f"skill: {i.get('skill', '')} {str(i.get('args', ''))[:60]}".strip()
        if n.startswith("mcp__tracker__"):
            return f"tracker: {n.split('__')[-1]}"
        return None

    def run(self) -> None:
        started = time.time()
        try:
            self.proc = subprocess.Popen(self.cmd, cwd=self.cwd, env=self.env, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, text=True, bufsize=1)
            for line in self.proc.stdout:
                if time.time() - started > self.timeout:
                    self.error = f"timed out after {self.timeout // 60} min"
                    self.proc.kill()
                    break
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("type") == "assistant":
                    for blk in (ev.get("message") or {}).get("content") or []:
                        if blk.get("type") == "tool_use":
                            d = self.describe(blk)
                            if d:
                                self.b.upsert_agent(self.name, activity=d)
                                if not d.startswith(("$ python3 .sdlc/bin/board.py", "$ python .sdlc/bin/board.py")):
                                    self.b.event(self.item_key, self.name, "activity", d)
                        elif blk.get("type") == "text" and blk.get("text", "").strip():
                            self.b.upsert_agent(self.name, activity="💭 " + blk["text"].strip()[:140])
                elif ev.get("type") == "result":
                    self.result_text = ev.get("result") or ""
                    self.cost = ev.get("total_cost_usd") or 0.0
                    if ev.get("is_error"):
                        self.error = (self.result_text or "claude reported an error")[:500]
            self.proc.wait(timeout=30)
            if self.proc.returncode and not self.error:
                self.error = (self.proc.stderr.read() or f"exit {self.proc.returncode}")[-500:]
        except Exception as e:  # never let one agent crash the team
            self.error = str(e)[:500]
        finally:
            self.b.add_cost(self.name, self.cost)

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


class SimulatedRun(AgentRun):
    """--simulate: scripted agents (no model calls) to exercise the board, hand-offs, merges and the kanban."""

    def __init__(self, *a, role: str = "developer", behaviour: str = "", **kw):
        super().__init__(*a, **kw)
        self.role, self.behaviour = role, behaviour

    def run(self) -> None:
        env = {**os.environ, **self.env}
        k = self.item_key
        def board(*args):
            subprocess.run([sys.executable, ".sdlc/bin/board.py", *args], cwd=self.cwd, env=env, capture_output=True)
        steps = 3
        for s in range(steps):
            self.b.upsert_agent(self.name, activity=f"{'coding' if self.role == 'developer' else 'testing'} {k} ({s + 1}/{steps})")
            self.b.event(k, self.name, "activity", f"edit src/{k.lower()}.py" if self.role == "developer"
                         else f"browser: navigate http://localhost/{k.lower()}")
            time.sleep(1.2)
        if self.role == "developer":
            Path(self.cwd, "src").mkdir(exist_ok=True)
            Path(self.cwd, "src", f"{k.lower()}.py").write_text(f"# {k} implemented by {self.name}\n")
            subprocess.run(["git", "add", "-A"], cwd=self.cwd, capture_output=True)
            subprocess.run(["git", "-c", "user.name=sim", "-c", "user.email=s@x", "commit", "-qm", f"{k}: implement"],
                           cwd=self.cwd, capture_output=True)
            if self.behaviour == "block":
                board("blocked", k, "Which date format does the API expect?")
            else:
                board("submit", k, "implemented; verify green")
        elif self.role == "qa":
            if self.behaviour == "fail":
                board("qa-fail", k, "Empty title is accepted; expected a validation error (400).")
            else:
                board("qa-pass", k, "All acceptance criteria checked in the browser; screenshot attached.")
        elif self.role == "helper":
            board("ask", self.behaviour or "developer", "Use ISO 8601 (YYYY-MM-DD); see spec FR-3.", "--task", k)
        elif self.role == "designer":
            d = Path(self.cwd, self.behaviour, "design")
            d.mkdir(parents=True, exist_ok=True)
            Path(self.cwd, "DESIGN.md").write_text("# DESIGN\n\nInk #0e0f12, lime #c6f432, Space Grotesk / Inter.\n")
            (d / "mockup.html").write_text("<!doctype html><title>Mockup</title><body style='font-family:sans-serif;"
                                           "background:#0e0f12;color:#ecedef;padding:40px'><h1>Bookmarks</h1>"
                                           "<p>Simulated mockup: form, list, search, tag chips, empty + error states.</p>")
            (d / "design-notes.md").write_text("# Design notes\n\nSimulated.\n")
            subprocess.run(["git", "add", "-A"], cwd=self.cwd, capture_output=True)
            subprocess.run(["git", "-c", "user.name=sim", "-c", "user.email=s@x", "commit", "-qm", f"{k}: design"],
                           cwd=self.cwd, capture_output=True)
            board("design-ready", k, "Dark ink + lime direction; 5 states per screen; see mockup.html.")


# ====================================================================== planning
PLAN_PROMPT = """You are the planner of an AI-native SDLC agent team. Break the accepted change at {rel} into an
Epic → Stories → Tasks breakdown that {devs} developer agents can build IN PARALLEL in separate git worktrees.

Read {rel}/intent.md, {rel}/spec.md and {rel}/plan.md (whichever exist), CLAUDE.md and the existing code.

Rules:
- One epic for the change. Stories follow the spec's user-facing capabilities (2–6 stories).
- Tasks are 15–60 minutes of agent work each, 2–5 per story. Each task lists the files it will create or change.
  Keep tasks file-disjoint where possible so parallel developers don't collide.
- If the project needs a skeleton (app entry point, package layout, test setup), make that the first task and
  let every other task depend on it.
- depends_on uses task ids from this file. No cycles.
- Each task has testable acceptance criteria and a "qa" note: how a QA agent proves it in a browser or via the API.
- Mark "ui": true on every task that creates or changes something a user sees (pages, components, styles, copy),
  and set the top-level "ui" true if the change has any UI. A designer agent designs those before they are built,
  so UI tasks wait for the design approval and everything else starts at once.
- Keep the skeleton and all backend/API/data tasks "ui": false and free of page, template, CSS or static files:
  put the first page/HTML shell in a UI task of its own. Otherwise the whole build waits for the design.

Do not write any files. Reply with ONLY the breakdown as one JSON object in a ```json block, exactly this shape:
{{"epic": {{"title": "...", "description": "..."}}, "ui": true,
  "stories": [{{"id": "S1", "title": "...", "description": "...", "acceptance": ["..."],
               "tasks": [{{"id": "T1", "title": "...", "description": "...", "files": ["..."],
                          "acceptance": ["..."], "qa": "...", "ui": false, "depends_on": []}}]}}]}}
"""


def cmd_plan(root: Path, cfg: dict, a) -> None:
    change = resolve_change(root, cfg, a.change)
    rel = change.relative_to(root).as_posix()
    if (header_field(change / "intent.md", "Status") or "") not in ("accepted", "approved"):
        sys.exit("intent.md must be Status: accepted before the team plans it")
    out = change / "breakdown.json"
    if not out.is_file() or a.replan:
        if a.simulate:
            out.write_text(json.dumps(SIM_BREAKDOWN, indent=2), encoding="utf-8")
        else:
            tcfg = cfg["team"]
            log(f"planner: breaking {change.name} into epic → stories → tasks")
            b = Board()
            b.upsert_agent("planner", role="planner", status="working", activity="planning")
            prompt, data, problem = PLAN_PROMPT.format(rel=rel, devs=a.developers or tcfg["developers"]), None, ""
            for attempt in range(2):  # the lead validates the JSON and writes the file itself
                r = AgentRun(b, "planner", root, prompt + (f"\n\nYour previous answer was rejected: {problem}. "
                             "Reply again with ONLY the corrected JSON." if problem else ""),
                             tcfg["models"]["planner"], BASE_TOOLS, None, 20,
                             plugin_dir=os.environ.get("SDLC_PLUGIN_DIR"))
                r.run()
                data = extract_json(r.result_text)
                problem = validate_breakdown(data) if data else f"no JSON found ({r.error or r.result_text[-200:]})"
                if not problem:
                    break
            b.upsert_agent("planner", status="idle", activity="breakdown ready" if not problem else problem[:140])
            if problem:
                sys.exit(f"planner could not produce a valid breakdown: {problem}")
            out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    data = json.loads(out.read_text(encoding="utf-8"))
    problem = validate_breakdown(data)
    if problem:
        sys.exit(f"{out.name} is not a valid breakdown: {problem}")
    load_breakdown(root, cfg, change, data, max(1, a.developers if a.developers is not None else cfg["team"]["developers"]))
    if not a.simulate and cfg["pipeline"].get("commit", True):
        git(root, "add", str(out))
        git(root, "commit", "-q", "-m", f"breakdown: {change.name}", "-m", "Epic/stories/tasks for the agent team.")
    sync_once(cfg)
    print_tree(Board())


def breakdown_sha(data: dict) -> str:
    return hashlib.sha1(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]


def board_untouched(b: Board) -> bool:
    """True while no agent has done any work: nothing past To Do and only the planner has run."""
    work = [i for i in b.items() if i["type"] in ("task", "design")]
    return all(i["status"] == "todo" for i in work) and not any(
        (a["runs"] or 0) > 0 for a in b.agents() if a["name"] != "planner")


def validate_breakdown(d: dict) -> str:
    """Empty string when the breakdown is usable, else what is wrong with it."""
    if not isinstance(d, dict) or not isinstance(d.get("epic"), dict) or not d["epic"].get("title"):
        return "missing epic.title"
    stories = d.get("stories")
    if not isinstance(stories, list) or not stories:
        return "no stories"
    ids = set()
    for s in stories:
        if not s.get("title") or not isinstance(s.get("tasks"), list) or not s["tasks"]:
            return f"story {s.get('id')} needs a title and at least one task"
        for t in s["tasks"]:
            if not t.get("id") or not t.get("title"):
                return "every task needs id and title"
            if t["id"] in ids:
                return f"duplicate task id {t['id']}"
            ids.add(t["id"])
    for s in stories:
        for t in s["tasks"]:
            bad = [x for x in t.get("depends_on", []) if x not in ids]
            if bad:
                return f"task {t['id']} depends on unknown {bad}"
    graph = {t["id"]: t.get("depends_on", []) for s in stories for t in s["tasks"]}
    seen, stack = set(), set()
    def cyc(n):
        if n in stack:
            return True
        if n in seen:
            return False
        seen.add(n); stack.add(n)
        hit = any(cyc(m) for m in graph[n])
        stack.discard(n)
        return hit
    if any(cyc(n) for n in graph):
        return "dependency cycle"
    return ""


def ui_world(root: Path, cfg: dict) -> tuple[str, str]:
    """brownfield when the repo already has a UI (or a DESIGN.md) the new work must match; else greenfield."""
    if (root / "DESIGN.md").is_file():
        return "brownfield", "DESIGN.md exists"
    globs = cfg["team"]["design"]["ui_globs"]
    files = [f for f in git(root, "ls-files").splitlines()
             if not f.startswith(("sdlc/", ".sdlc/", "tests/", "test/", "evals/", ".claude/", ".github/", ".gitlab/"))]
    ui = [f for f in files if matches_any(f, globs)]
    return ("brownfield", f"existing UI files: {', '.join(ui[:5])}") if ui else ("greenfield", "no UI in the repo yet")


def load_breakdown(root: Path, cfg: dict, change: Path, data: dict, devs: int) -> None:
    b = Board()
    sha = breakdown_sha(data)
    if b.items(type_="epic"):
        m = b.meta()
        existing = m.get("change")
        if existing == change.name and m.get("breakdown_sha") == sha:
            log("board already holds this breakdown — keeping it")
            return
        if board_untouched(b):
            # nothing has been worked on yet, so reloading loses nothing — no human reset needed
            log(f"breakdown changed and no work has started — reloading the board"
                + (f" (was {existing})" if existing != change.name else ""))
            b.clear()
        elif existing == change.name and m.get("breakdown_sha") is None:
            b.set_meta(breakdown_sha=sha)  # board from an older kit with work in progress: adopt, keep it
            return
        elif existing == change.name:
            log("breakdown.json changed but agents have already worked on this board — keeping the board. "
                "To start over, a human runs: python .sdlc/bin/team.py reset")
            return
        else:
            sys.exit(f"the board holds another change ({existing}) with work in progress; a human runs team.py reset first")
    b.set_meta(change=change.name, project=root.name, created_at=utcnow(), status="planned", breakdown_sha=sha,
               tracker=(cfg.get("tracker") or {}).get("type", "internal"),
               integration_branch=f"{cfg['team']['branch_prefix']}{change.name}")
    e = b.add_item("epic", data["epic"]["title"], description=data["epic"].get("description", ""))
    idmap, dev_names = {}, [f"dev-{i + 1}" for i in range(devs)]
    pending = []
    for s in data["stories"]:
        sk = b.add_item("story", s["title"], e, description=s.get("description", ""),
                        acceptance=s.get("acceptance", []))
        for t in s.get("tasks", []):
            desc = t.get("description", "") + (f"\n\nQA: {t['qa']}" if t.get("qa") else "")
            tk = b.add_item("task", t["title"], sk, description=desc, acceptance=t.get("acceptance", []),
                            files=t.get("files", []))
            idmap[t["id"]] = tk
            # the planner's explicit flag wins; file globs only decide when it said nothing
            is_ui = bool(t["ui"]) if "ui" in t else \
                any(matches_any(f, cfg["team"]["design"]["ui_globs"]) for f in t.get("files", []))
            pending.append((tk, t.get("depends_on", []), is_ui))
    # guard: never hold backend work for the design. A "UI" task that any non-UI task depends on (directly or
    # through others) is foundation work, e.g. a skeleton with a placeholder page, so it does not wait for D-1.
    by_id = {idmap[t["id"]]: [idmap[d] for d in t.get("depends_on", []) if d in idmap]
             for s in data["stories"] for t in s.get("tasks", [])}
    needed_by_backend, stack = set(), [tk for tk, _d, ui in pending if not ui]
    while stack:
        for dep in by_id.get(stack.pop(), []):
            if dep not in needed_by_backend:
                needed_by_backend.add(dep); stack.append(dep)
    freed = [tk for tk, _d, ui in pending if ui and tk in needed_by_backend]
    pending = [(tk, d, ui and tk not in needed_by_backend) for tk, d, ui in pending]
    # design: a designer agent designs every UI task before it is built (backend tasks don't wait)
    dmode = cfg["team"]["design"]["mode"]
    ui_tasks = [tk for tk, _d, is_ui in pending if is_ui]
    need = dmode == "always" or (dmode == "auto" and (bool(data.get("ui")) or bool(ui_tasks)))
    design_key = None
    if need:
        world, evidence = ui_world(root, cfg)
        design_key = b.add_item("design", f"Design: {data['epic']['title']}", e,
                                description=f"{world} design ({evidence}). Covers {', '.join(ui_tasks) or 'all UI'}.",
                                acceptance=["DESIGN.md is the standard (created for greenfield, followed for brownfield)",
                                            "mockup.html shows every screen and state the UI tasks need",
                                            "The human approves the design"])
        b.update(design_key, "lead", assignee="designer")
        b.set_meta(design={"key": design_key, "mode": world, "evidence": evidence, "ui_tasks": ui_tasks})
        b.event(design_key, "lead", "assign", f"{world}: designer designs {len(ui_tasks)} UI task(s) first")
        if freed:
            b.event(design_key, "lead", "system", f"{', '.join(freed)} touch UI files but backend work depends on "
                                                  "them — they start now instead of waiting for the design")
            log(f"{', '.join(freed)}: backend depends on them — not waiting for the design")
    # dependencies, then a first assignment that spreads the work (the lead rebalances at run time)
    load = {d: 0 for d in dev_names}
    for tk, deps, is_ui in pending:
        keys = [idmap[d] for d in deps if d in idmap] + ([design_key] if design_key and is_ui else [])
        owner = min(load, key=load.get)
        load[owner] += 1
        b.update(tk, "lead", depends_on=json.dumps(keys), assignee=owner)
        b.event(tk, "lead", "assign", f"assigned to {owner}")
    b.event(None, "lead", "system", f"plan loaded: {len(data['stories'])} stories, {len(pending)} tasks, "
                                    f"{devs} developers" + (f", design {design_key} first for {len(ui_tasks)} UI task(s)"
                                                            if design_key else ", no UI — no designer needed"))


def print_tree(b: Board) -> None:
    for e in b.items(type_="epic"):
        print(f"\n{e['key']}  {e['title']}  [{STATUS_LABEL.get(e['status'], e['status'])}]  {e.get('ext_url') or ''}")
        for d in b.items(type_="design", parent_key=e["key"]):
            print(f"  {d['key']}  {d['title']}  [{STATUS_LABEL.get(d['status'], d['status'])}]  designer · "
                  f"{(b.meta().get('design') or {}).get('mode', '')}")
        for s in b.items(type_="story", parent_key=e["key"]):
            print(f"  {s['key']}  {s['title']}  [{STATUS_LABEL.get(s['status'], s['status'])}]")
            for t in b.items(parent_key=s["key"]):
                deps = f" after {','.join(t['depends_on'])}" if t["depends_on"] else ""
                print(f"     {t['key']:5} {t['title'][:60]:60} {t['assignee'] or '-':6} "
                      f"{STATUS_LABEL.get(t['status'], t['status'])}{deps}")


def sync_once(cfg: dict) -> None:
    try:
        client = trackers.make(cfg)
    except trackers.TrackerError as e:
        log(f"tracker not configured correctly, internal board only: {e}")
        return
    if client:
        errs = trackers.Sync(Board(), client).run()
        log(f"synced to {client.name}" + (f" ({len(errs)} errors — see board)" if errs else ""))


SIM_BREAKDOWN = {
    "epic": {"title": "Bookmarks manager", "description": "Save, tag and search links."}, "ui": True,
    "stories": [
        {"id": "S1", "title": "Save bookmarks", "acceptance": ["A user can save a URL with a title"],
         "tasks": [{"id": "T1", "title": "Project skeleton and data model", "files": ["src/t-1.py"], "depends_on": []},
                   {"id": "T2", "title": "POST /api/bookmarks", "files": ["src/t-2.py"], "depends_on": ["T1"]},
                   {"id": "T3", "title": "Add-bookmark form", "files": ["src/t-3.py"], "ui": True, "depends_on": ["T1"]}]},
        {"id": "S2", "title": "Find bookmarks", "acceptance": ["Search by title and tag"],
         "tasks": [{"id": "T4", "title": "Search endpoint", "files": ["src/t-4.py"], "depends_on": ["T1"]},
                   {"id": "T5", "title": "Tag filter chips", "files": ["src/t-5.py"], "ui": True, "depends_on": ["T3"]},
                   {"id": "T6", "title": "Date range filter", "files": ["src/t-6.py"], "depends_on": ["T4"]}]},
    ]}


# ====================================================================== the lead
DEV_PROMPT = """You are {agent}, a developer on an AI-native SDLC agent team (teammates: {others}).
Your own git worktree is {wt} on branch {branch}. Work only there; other developers work in parallel.

YOUR TASK {key}: {title}
{description}
Files you own for this task: {files}
Acceptance criteria:
{acceptance}

It belongs to story {story_key} "{story_title}" of epic "{epic_title}". For the big picture read
{rel}/intent.md, {rel}/spec.md, {rel}/plan.md and {rel}/breakdown.json. Follow CLAUDE.md.
{extra}
How to work:
1. Check messages first: {cli} inbox  (check again after each major step — teammates may answer you).
2. Implement the task. New packages go into the manifest (requirements.txt / package.json) and are installed by
   `python3 .sdlc/bin/sdlc.py verify setup` — never pip/npm install by hand.
3. Write or extend tests for the acceptance criteria. Run `python3 .sdlc/bin/sdlc.py verify` until it is green.
   Fix the code, never weaken a test.
4. Commit on your branch: git add -A && git commit -m "{key}: <what>"
5. Talk to the team when it helps: {cli} ask <dev-N|qa|developer> "question" --task {key}   ·   {cli} comment {key} "progress"
   If you cannot continue without a teammate or a human: {cli} blocked {key} "exactly what you need"  — then stop.
6. When verify is green and everything is committed: {cli} submit {key} "what you built and how QA can test it"  — then stop.
"""

QA_PROMPT = """You are {agent}, the QA engineer on an AI-native SDLC agent team (developers: {devs}).
{dev} handed you task {key}: {title}
{description}
Acceptance criteria:
{acceptance}
Story {story_key} "{story_title}" acceptance: {story_acceptance}

The code is checked out in your own worktree {wt} (branch {branch}).
{app}
Do this:
1. {cli} inbox — then run `python3 .sdlc/bin/sdlc.py verify` (setup, build, tests, lint).
2. Test every acceptance criterion the way a user would. {browser}
   For APIs use curl. Try the edge cases a careful tester would (empty input, bad input, refresh, repeat).
3. If a criterion has no automated test, add one under tests/ (e2e or API) and commit it:
   git add -A && git commit -m "{key}: QA tests"   — do NOT change application code yourself.
4. Unclear behaviour? Ask the developer: {cli} ask {dev} "question" --task {key}
5. Verdict — exactly one, then stop:
   {cli} qa-pass {key} "what you checked and the evidence"
   {cli} qa-fail {key} "steps to reproduce · expected · actual"
"""

HELP_PROMPT = """You are {agent} on an AI-native SDLC agent team. Your teammate {dev} is BLOCKED on task {key}: {title}
Their message: "{reason}"

Their worktree is {wt} — read it with Read/Grep/Glob (do NOT edit it). Also read {rel}/spec.md and {rel}/plan.md.
Work out the answer or the fix, then send it to them with concrete steps, file names and code snippets:
  {cli} ask {dev} "<your answer>" --task {key}
If it really needs a human decision, say so in the same message and also run:
  {cli} ask lead "<the decision needed>" --task {key}
Then stop.
"""


DESIGN_PROMPT = """You are the designer on an AI-native SDLC agent team. Design the UI for epic "{epic_title}" BEFORE
the developers build it. A human reviews your mockup and must approve it.

Mode: {mode} ({evidence})
{mode_rules}

Your own git worktree is {wt} on branch {branch}. Work only there.
Read {rel}/intent.md, {rel}/spec.md, {rel}/plan.md, {rel}/breakdown.json (whichever exist), CLAUDE.md, PRODUCT.md and
DESIGN.md if present, and the existing UI code.

UI tasks the developers will build from your design:
{ui_tasks}

Use the impeccable design skill. Load it with the Skill tool (name: impeccable) and follow its Setup, then:
{impeccable_steps}
You cannot ask the human questions in this run: take answers from the intent and spec, and list every assumption in
design-notes.md. If the impeccable skill is not available, write that in design-notes.md and apply the same
discipline yourself (clear hierarchy, real copy, accessible contrast, every state designed, no generic AI look).

Deliverables — commit all of them:
1. DESIGN.md at the repo root: the design standard (tokens: color, type, spacing, radius, shadow; components; states).
2. {rel}/design/mockup.html — ONE self-contained file (inline CSS/JS; only Google Fonts may load from the web) that
   shows every screen and state the UI tasks need: default, filled, empty, loading, validation/error, hover/focus,
   at desktop width and inside a 390px mobile frame. Real copy from the spec — no lorem ipsum. Use the DESIGN.md
   tokens as CSS variables so developers can lift them directly.
3. {rel}/design/design-notes.md — the direction in two sentences, screens, components, tokens, interactions,
   accessibility, assumptions, and for EACH UI task key exactly what to build and which part of the mockup it is.
4. Check it before you submit: open {mockup_url} in the browser tool at 1280px and 390px wide, look at it, fix what
   is off{critique}.

Then commit (git add -A && git commit -m "{key}: design") and run:
  {cli} design-ready {key} "two-sentence summary: the direction, the screens, what the reviewer should look at"
and stop.
{feedback}"""

DESIGN_MODES = {
    "greenfield": ("There is no UI yet: you set the visual standard everyone else follows.",
                   "- run its init flow to write PRODUCT.md (product context) from the intent/spec;\n"
                   "- treat this as new work: choose a distinct, fitting visual direction and write DESIGN.md;\n"
                   "- use its shape flow to plan each screen, then build the mockup."),
    "brownfield": ("The app already has a look. DESIGN.md (or the existing UI) is the standard: new screens must look "
                   "like they always belonged. Do NOT redesign, re-theme or change existing tokens; add only the new "
                   "components and patterns this change needs, in the same style.",
                   "- if DESIGN.md is missing, run its document flow first to generate DESIGN.md from the existing code;\n"
                   "- if PRODUCT.md is missing, run its init flow from the intent/spec;\n"
                   "- use its shape flow for the new screens only, then build the mockup that reuses existing tokens."),
}

DESIGN_FOR_DEV = """
APPROVED DESIGN — build this task's UI to match it exactly: {rel}/design/mockup.html (open {mockup_url} in a
browser if you have one) and DESIGN.md: layout, tokens (CSS variables), type, spacing, copy and every state.
{rel}/design/design-notes.md says what belongs to {key}. Don't invent new styles; if the design lacks something you
need, ask: {cli} ask designer "..." --task {key}
"""

DESIGN_FOR_QA = """
DESIGN CHECK — this task has an approved design. Open the mockup {mockup_url} and the running page in the browser at
the same widths (1280 and 390) and compare them side by side, the way a designer reviewing a screenshot would.
Fail the task only for deviations a user would notice: wrong or missing layout, element, state or copy; a colour or
font that is not from DESIGN.md; broken responsive layout or horizontal scroll; spacing or size visibly off
(more than ~8px or ~20%). Do NOT fail for sub-pixel or few-pixel differences, slightly different icon sizes/stroke
widths, or anything you only find by measuring with getComputedStyle — list those under "Design nits" in a PASS.
"""


# Windows: `python3` is often missing or the Microsoft Store stub, so agents are told to use `python`
PY = "python" if os.name == "nt" else "python3"
if PY != "python3":
    for _n, _v in list(globals().items()):
        if _n.isupper() and isinstance(_v, str) and "python3 " in _v:
            globals()[_n] = _v.replace("python3 ", PY + " ")


class Lead:
    def __init__(self, root: Path, cfg: dict, change: Path, a):
        self.root, self.cfg, self.change, self.a = root, cfg, change, a
        self.t = cfg["team"]
        self.b = Board()
        self.rel = change.relative_to(root).as_posix()
        self.integration = f"{self.t['branch_prefix']}{change.name}"
        self.wt_root = root / self.t["worktree_dir"]
        self.devs = [f"dev-{i + 1}" for i in range(a.developers if a.developers is not None else self.t["developers"])]
        self.qas = [f"qa-{i + 1}" for i in range(a.qa if a.qa is not None else self.t["qa_agents"])]
        self.running: dict[str, tuple[threading.Thread, AgentRun, str, str]] = {}  # agent -> (thread, run, task, kind)
        self.attempts: dict[str, int] = {}
        self.help_rounds: dict[str, int] = {}
        self.escalated: set[str] = set(self.b.meta().get("escalated", []))
        self.stop = threading.Event()
        try:
            self.tracker = trackers.make(cfg)
        except trackers.TrackerError as e:
            log(f"tracker disabled: {e}")
            self.tracker = None
        self.sync = trackers.Sync(self.b, self.tracker) if self.tracker else None
        self.sim_counter = 0
        self.d = self.t["design"]
        self.design = self.b.meta().get("design")          # {"key", "mode", ...} or None
        self.designers = ["designer"] if self.design else []
        self._design_srv = None
        self._waiting_note = 0

    # ---------------------------------------------------------------- setup
    def wt(self, name: str) -> Path:
        return self.wt_root / name

    def setup(self) -> None:
        if not git(self.root, "rev-parse", "--verify", "--quiet", self.integration):
            git(self.root, "branch", self.integration, "HEAD")
            log(f"created integration branch {self.integration}")
        self.wt_root.mkdir(parents=True, exist_ok=True)
        for name in ["integration", *self.devs, *self.qas, *self.designers]:
            p = self.wt(name)
            if not (p / ".git").exists():
                args = ["worktree", "add", str(p), self.integration] if name == "integration" else \
                       ["worktree", "add", "--detach", str(p), self.integration]
                r = sh(["git", *args], self.root)
                if r.returncode:
                    sys.exit(f"git worktree add {name} failed: {r.stderr}")
                log(f"worktree {name} → {p.relative_to(self.root)}")
            role = "developer" if name.startswith("dev") else "qa" if name.startswith("qa") else \
                   "designer" if name == "designer" else None
            if role:
                self.b.upsert_agent(name, role=role, status="idle", item_key=None, activity="ready",
                                    worktree=str(p.relative_to(self.root)))
        self.b.set_meta(status="running", started_at=utcnow(), integration_branch=self.integration,
                        team={"developers": self.devs, "qa": self.qas, "designers": self.designers})
        if self.design:
            self.start_design_server()
        self.b.event(None, "lead", "system", f"team started: {', '.join(self.designers + self.devs + self.qas)}")

    def start_design_server(self) -> None:
        """Serve the worktrees' design folders on localhost so designer, devs, QA and the human see the mockup."""
        port = self.d.get("design_port", 8690)
        handler = functools.partial(SimpleHTTPRequestHandler, directory=str(self.wt_root))
        handler.log_message = lambda *a, **k: None
        try:
            self._design_srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
        except OSError as e:
            log(f"design preview server not started on :{port}: {e}")
            return
        threading.Thread(target=self._design_srv.serve_forever, daemon=True).start()
        self.design["preview_base"] = f"http://127.0.0.1:{port}"
        self.b.set_meta(design=self.design)

    def mockup_url(self, where: str = "integration") -> str:
        base = (self.design or {}).get("preview_base")
        rel = f"{where}/{self.rel}/design/mockup.html"
        return f"{base}/{rel}" if base else str(self.wt_root / rel)

    def env_for(self, agent: str, role: str) -> dict:
        env = {"SDLC_AGENT": agent, "SDLC_ROLE": role, "SDLC_BOARD_DB": str(self.b.path)}
        if self.tracker:
            env.update(self.tracker.mcp_env())
        return env

    def mcp_for(self, role: str, port: int | None = None) -> dict:
        servers = {}
        if self.tracker:
            servers.update(self.tracker.mcp_config())
        if role in ("qa", "designer") and self.t["qa"].get("browser") == "playwright-mcp":
            args = ["-y", "@playwright/mcp@latest", "--headless", "--isolated"]
            if self.t["qa"].get("browser_executable"):
                args += ["--executable-path", self.t["qa"]["browser_executable"]]
            args += list(self.t["qa"].get("browser_args") or [])  # e.g. ["--no-sandbox"] when running as root
            servers["playwright"] = {"command": "npx", "args": args}
        return servers or None

    def tools_for(self, role: str) -> list[str]:
        extra = [f"Bash({c})" for c in self.cfg["verify"].values() if c]
        extra += [f"Bash({c})" for c in self.t.get("allowed_bash", []) + self.cfg["pipeline"].get("allowed_bash", [])]
        mcp = ["mcp__tracker"] if self.tracker else []
        if role == "developer":
            return BASE_TOOLS + EDIT_TOOLS + SAFE_BASH + DEV_BASH + extra + mcp
        if role == "qa":
            pw = ["mcp__playwright"] if self.t["qa"].get("browser") == "playwright-mcp" else []
            return BASE_TOOLS + EDIT_TOOLS + SAFE_BASH + QA_BASH + extra + mcp + pw
        if role == "designer":
            pw = ["mcp__playwright"] if self.t["qa"].get("browser") == "playwright-mcp" else []
            return BASE_TOOLS + EDIT_TOOLS + SAFE_BASH + ["Skill", "Bash(*impeccable*)", "Bash(npx impeccable*)"] + \
                extra + mcp + pw
        return BASE_TOOLS + ["Bash(python3 .sdlc/bin/board.py *)", "Bash(python .sdlc/bin/board.py *)"] + mcp

    # ---------------------------------------------------------------- helpers
    def tasks(self) -> list[dict]:
        return self.b.items(type_="task")

    def busy(self, agent: str) -> bool:
        return agent in self.running

    def idle(self, names: list[str]) -> list[str]:
        return [n for n in names if not self.busy(n)]

    def ready(self, t: dict) -> bool:
        return all((self.b.item(d) or {}).get("status") == "done" for d in t["depends_on"])

    def file_clash(self, t: dict) -> str | None:
        mine = set(t["files"])
        for other in self.tasks():
            if other["key"] != t["key"] and other["status"] in ("in_progress", "blocked") and mine & set(other["files"]):
                if any(r[2] == other["key"] for r in self.running.values()):
                    return other["key"]
        return None

    def context(self, t: dict) -> dict:
        story = self.b.item(t["parent_key"]) or {}
        epic = self.b.item(story.get("parent_key") or "") or {}
        return {"key": t["key"], "title": t["title"], "description": t["description"] or "(see story)",
                "files": ", ".join(t["files"]) or "(decide, keep it small)",
                "acceptance": "\n".join(f"- {x}" for x in t["acceptance"]) or "- see story",
                "story_key": story.get("key"), "story_title": story.get("title"),
                "story_acceptance": "; ".join(story.get("acceptance") or []) or "-",
                "epic_title": epic.get("title"), "rel": self.rel, "cli": BOARD_CLI}

    def launch(self, agent: str, role: str, kind: str, t: dict, prompt: str, cwd: Path, model: str,
               add_dirs=None, port=None, behaviour="") -> None:
        if self.a.simulate:
            run = SimulatedRun(self.b, agent, cwd, prompt, model, [], t["key"], 5,
                               extra_env=self.env_for(agent, role), role=kind, behaviour=behaviour)
        else:
            run = AgentRun(self.b, agent, cwd, prompt, model, self.tools_for(role), t["key"],
                           self.t["run_timeout_minutes"], mcp=self.mcp_for(role, port),
                           extra_env=self.env_for(agent, role), add_dirs=add_dirs,
                           plugin_dir=[os.environ.get("SDLC_PLUGIN_DIR")] +
                                      (list(self.d.get("plugin_dirs") or []) if role == "designer" else []))
        th = threading.Thread(target=run.run, daemon=True, name=f"{agent}:{t['key']}")
        self.running[agent] = (th, run, t["key"], kind)
        self.b.upsert_agent(agent, status="helping" if kind == "helper" else "designing" if kind == "designer" else "working",
                            item_key=t["key"],
                            activity=f"started {kind} on {t['key']}")
        th.start()
        log(f"{agent} → {kind} {t['key']} {t['title'][:60]}")

    # ---------------------------------------------------------------- dispatch
    def start_dev(self, agent: str, t: dict) -> None:
        wt = self.wt(agent)
        branch = t.get("branch") or f"{self.integration}--{t['key']}"  # not "/": git can't nest under a branch
        if t.get("branch"):  # returning work (QA fail, conflict, help): keep the branch
            r = sh(["git", "checkout", "-q", branch], wt)
            qa_branch = f"qa/{t['key']}"
            if git(self.root, "rev-parse", "--verify", "--quiet", qa_branch):
                sh(["git", "merge", "-q", "--no-edit", qa_branch], wt)  # keep QA's tests
        else:
            sh("git reset -q --hard && git clean -qfd", wt)
            r = sh(["git", "checkout", "-q", "-B", branch, self.integration], wt)
        if r.returncode:
            self.escalate(t, f"could not check out {branch} in {agent}'s worktree: {r.stderr.strip()[:200]}")
            return
        others = ", ".join(n for n in self.devs + self.qas if n != agent)
        extra = ""
        fails = [e for e in self.b.events(item_key=t["key"], limit=50) if e["kind"] == "qa" and e["text"].startswith("FAIL")]
        if fails:
            extra += f"\nQA SENT THIS BACK (round {len(fails)}): {fails[-1]['text'][6:]}\nFix it, then submit again.\n"
        if self.b.meta().get(f"conflict:{t['key']}"):
            extra += (f"\nYOUR BRANCH CONFLICTS with {self.integration}. Run `git merge {self.integration}`, resolve the "
                      "conflicts keeping both features, run verify, commit, submit again.\n")
        helps = [m for m in self.b.messages(item_key=t["key"]) if m["recipient"] == agent and m["sender"] != agent]
        if helps:
            extra += "\nMessages from your team about this task:\n" + "\n".join(
                f"- {m['sender']}: {m['text']}" for m in helps[-5:]) + "\n"
        if self.design and self.design["key"] in t["depends_on"]:
            extra += DESIGN_FOR_DEV.format(rel=self.rel, mockup_url=self.mockup_url(), key=t["key"], cli=BOARD_CLI)
        ctx = {**self.context(t), "agent": agent, "others": others, "wt": wt, "branch": branch, "extra": extra}
        self.b.update(t["key"], "lead", status="in_progress", assignee=agent, branch=branch)
        behaviour = "block" if self.a.simulate and t["key"] == "T-4" and not self.help_rounds.get("T-4") else ""
        self.launch(agent, "developer", "developer", t, DEV_PROMPT.format(**ctx), wt,
                    self.t["models"]["developer"], behaviour=behaviour)

    def start_qa(self, agent: str, t: dict) -> None:
        wt = self.wt(agent)
        qa_branch = f"qa/{t['key']}"
        sh("git reset -q --hard && git clean -qfd", wt)
        r = sh(["git", "checkout", "-q", "-B", qa_branch, t["branch"]], wt)
        if r.returncode:
            self.escalate(t, f"QA could not check out {t['branch']}: {r.stderr.strip()[:200]}")
            return
        port = self.t["qa"]["port_base"] + self.qas.index(agent)
        app = self.start_app(agent, wt, port)
        self.b.update(t["key"], "lead", qa_by=agent)
        self.b.event(t["key"], "lead", "assign", f"QA {agent} picked up {t['key']} from {t['assignee']}")
        browser = ("Use the browser tools (mcp__playwright__browser_navigate, browser_snapshot, browser_click, "
                   "browser_type, browser_take_screenshot) against the running app."
                   if self.t["qa"].get("browser") == "playwright-mcp" else
                   "Drive the UI with Playwright scripts (npx playwright / python playwright).")
        ctx = {**self.context(t), "agent": agent, "devs": ", ".join(self.devs), "dev": t["assignee"], "wt": wt,
               "branch": qa_branch, "browser": browser,
               "app": f"The lead started the app for you at {app}." if app else
                      "No app server is configured (team.qa.start_cmd); test through tests, API calls and files."}
        behaviour = "fail" if self.a.simulate and t["key"] == "T-2" and not t["qa_rounds"] else ""
        prompt = QA_PROMPT.format(**ctx)
        if self.design and self.design["key"] in t["depends_on"]:
            prompt += DESIGN_FOR_QA.format(mockup_url=self.mockup_url())
        self.launch(agent, "qa", "qa", t, prompt, wt, self.t["models"]["qa"], port=port, behaviour=behaviour)

    def start_design(self, d: dict) -> None:
        agent, wt = "designer", self.wt("designer")
        branch = d.get("branch") or f"{self.integration}--{d['key']}"
        if d.get("branch"):
            r = sh(["git", "checkout", "-q", branch], wt)
        else:
            sh("git reset -q --hard && git clean -qfd", wt)
            r = sh(["git", "checkout", "-q", "-B", branch, self.integration], wt)
        if r.returncode:
            self.escalate(d, f"could not check out {branch} for the designer: {r.stderr.strip()[:200]}")
            return
        mode = self.design.get("mode", "greenfield")
        rules, steps = DESIGN_MODES[mode]
        ui = [self.b.item(k) for k in self.design.get("ui_tasks", [])]
        ui_text = "\n".join(f"- {t['key']} {t['title']}: " + "; ".join(t["acceptance"]) for t in ui if t) or "- (all UI)"
        changes = [e["text"][9:] for e in self.b.events(item_key=d["key"], limit=80)
                   if e["kind"] == "design" and e["text"].startswith("CHANGES:")]
        feedback = (f"\nTHE HUMAN ASKED FOR CHANGES (round {len(changes)}): {changes[-1]}\n"
                    "Update the design (keep what they did not mention), then design-ready again.\n") if changes else ""
        epic = self.b.item(d["parent_key"]) or {}
        prompt = DESIGN_PROMPT.format(
            epic_title=epic.get("title", ""), mode=mode, evidence=self.design.get("evidence", ""), mode_rules=rules,
            impeccable_steps=steps, wt=wt, branch=branch, rel=self.rel, ui_tasks=ui_text, key=d["key"], cli=BOARD_CLI,
            mockup_url=self.mockup_url("designer"), feedback=feedback,
            critique="; if the impeccable skill is loaded, run its critique and audit on the mockup and fix the findings")
        self.b.update(d["key"], "lead", status="in_progress", branch=branch)
        self.launch(agent, "designer", "designer", d, prompt, wt, self.t["models"].get("designer", "sonnet"),
                    behaviour=self.rel)

    def start_help(self, agent: str, t: dict) -> None:
        reason = next((e["text"].split(": ", 1)[-1] for e in reversed(self.b.events(item_key=t["key"], limit=50))
                       if e["kind"] == "status" and "Blocked" in e["text"]), "see the task history")
        ctx = {**self.context(t), "agent": agent, "dev": t["assignee"], "wt": self.wt(t["assignee"]),
               "reason": reason}
        self.help_rounds[t["key"]] = self.help_rounds.get(t["key"], 0) + 1
        self.b.event(t["key"], "lead", "help", f"{agent} sent to help {t['assignee']} (round {self.help_rounds[t['key']]})")
        cwd = self.wt(agent)
        self.launch(agent, "helper", "helper", t, HELP_PROMPT.format(**ctx), cwd, self.t["models"]["helper"],
                    add_dirs=[str(self.wt(t["assignee"]))], behaviour=t["assignee"])

    # ---------------------------------------------------------------- app for QA
    def start_app(self, agent: str, wt: Path, port: int) -> str | None:
        cmd = (self.t["qa"].get("start_cmd") or "").strip()
        if not cmd or self.a.simulate:
            return None
        setup = self.cfg["verify"].get("setup")
        if setup:
            sh(setup, wt, timeout=900)
        proc = subprocess.Popen(cmd.replace("{port}", str(port)), shell=True, cwd=wt, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, env={**os.environ, "PORT": str(port)}, start_new_session=True)
        self.apps = getattr(self, "apps", {})
        self.apps[agent] = proc
        url = f"http://127.0.0.1:{port}"
        deadline = time.time() + self.t["qa"].get("start_timeout", 60)
        while time.time() < deadline:
            try:
                urllib.request.urlopen(url + self.t["qa"].get("health_path", "/"), timeout=2)
                return url
            except urllib.error.HTTPError:
                return url  # server answers; a 4xx on the health path is fine
            except Exception:
                time.sleep(1)
        log(f"{agent}: app did not answer on {url} within the timeout")
        return url + " (it did not answer the health check — report that if it stays down)"

    def stop_app(self, agent: str) -> None:
        p = getattr(self, "apps", {}).pop(agent, None)
        if p and p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except Exception:
                p.terminate()

    # ---------------------------------------------------------------- after a run
    def finished(self, agent: str) -> None:
        th, run, key, kind = self.running.pop(agent)
        t = self.b.item(key)
        if run.error:
            self.b.event(key, agent, "system", f"{kind} run error: {run.error[:300]}")
        if kind == "developer":
            wt = self.wt(agent)
            if sh(["git", "status", "--porcelain"], wt).stdout.strip():
                sh("git add -A", wt)
                sh(["git", "-c", f"user.name={agent}", "-c", "user.email=agents@sdlc.local", "commit", "-qm",
                    f"{key}: uncommitted work from {agent}"], wt)
            if t["status"] == "in_progress":
                n = self.attempts[key] = self.attempts.get(key, 0) + 1
                if n >= self.t["max_dev_attempts"]:
                    self.escalate(t, f"{agent} ran {n} times without submitting")
                else:
                    self.b.event(key, "lead", "system", f"{agent} stopped without submitting — retrying")
            elif t["status"] == "in_qa":
                self.attempts.pop(key, None)
                self.b.set_meta(**{f"conflict:{key}": False})
        elif kind == "qa":
            self.stop_app(agent)
            sh(["git", "checkout", "-q", "--detach"], self.wt(agent))  # free qa/<task> for any QA agent
            if t["status"] == "in_qa" and not (t.get("qa_by") or "").startswith("pass:"):
                n = self.attempts[f"qa:{key}"] = self.attempts.get(f"qa:{key}", 0) + 1
                if n >= 2:
                    self.escalate(t, f"QA could not reach a verdict ({run.error or 'no qa-pass/qa-fail'})")
                else:
                    self.b.update(key, "lead", qa_by=None)  # no verdict: another QA run picks it up
                    self.b.event(key, "lead", "system", f"{agent} gave no verdict — QA will retry. Its last words: "
                                                        f"{(run.result_text or run.error or '-')[-300:]}")
            if (t.get("qa_rounds") or 0) >= self.t["max_qa_rounds"] and t["status"] != "in_qa":
                self.escalate(t, f"failed QA {t['qa_rounds']} times")
        elif kind == "designer":
            wt = self.wt(agent)
            if sh(["git", "status", "--porcelain"], wt).stdout.strip():
                sh("git add -A", wt)
                sh(["git", "-c", "user.name=designer", "-c", "user.email=agents@sdlc.local", "commit", "-qm",
                    f"{key}: uncommitted design work"], wt)
            if t["status"] == "in_progress":
                n = self.attempts[key] = self.attempts.get(key, 0) + 1
                if n >= self.t["max_dev_attempts"]:
                    self.escalate(t, f"designer ran {n} times without submitting a design")
                else:
                    self.b.event(key, "lead", "system", "designer stopped without design-ready — retrying. Last words: "
                                                        f"{(run.result_text or run.error or '-')[-300:]}")
            elif t["status"] == "review":
                self.attempts.pop(key, None)
                log(f"design {key} is ready — waiting for the human to approve it on the board")
        elif kind == "helper":
            if t["status"] == "blocked":
                if self.help_rounds.get(key, 0) >= self.t["max_help_rounds"]:
                    self.escalate(t, "still blocked after team help")
                else:
                    self.b.update(key, "lead", note=f"{agent} answered — back to {t['assignee']}", status="in_progress")
        self.b.upsert_agent(agent, status="idle", item_key=None, activity=f"finished {kind} {key}")

    def escalate(self, t: dict, why: str) -> None:
        self.escalated.add(t["key"])
        self.b.set_meta(escalated=sorted(self.escalated))
        self.b.update(t["key"], "lead", note=f"ESCALATED to a human: {why}", status="blocked")
        self.b.send("lead", "human", f"{t['key']} needs you: {why}", t["key"])
        log(f"ESCALATED {t['key']}: {why}")

    # ---------------------------------------------------------------- merging
    def merge(self, t: dict) -> None:
        iwt = self.wt("integration")
        src = f"qa/{t['key']}" if git(self.root, "rev-parse", "--verify", "--quiet", f"qa/{t['key']}") else t["branch"]
        who = (f"designer, approved by {t['qa_by'].split(':')[-1]}" if t["type"] == "design" else
               f"dev {t['assignee']}, QA {t['qa_by'].split(':')[-1]}")
        r = sh(["git", "-c", "user.name=team-lead", "-c", "user.email=lead@sdlc.local", "merge", "--no-ff", "-q",
                "-m", f"{t['key']}: {t['title']} ({who})", src], iwt)
        if r.returncode:
            sh(["git", "merge", "--abort"], iwt)
            n = self.attempts[f"merge:{t['key']}"] = self.attempts.get(f"merge:{t['key']}", 0) + 1
            if n >= 3:
                self.escalate(t, f"merge into {self.integration} failed {n} times: {(r.stderr or r.stdout).strip()[:200]}")
                return
            self.b.set_meta(**{f"conflict:{t['key']}": True})
            self.b.update(t["key"], "lead", note=f"merge conflict with {self.integration} — back to {t['assignee']}",
                          status="in_progress", qa_by=None)
            self.b.send("lead", t["assignee"], f"{t['key']} conflicts with {self.integration}; merge it into your "
                                               "branch, resolve, re-run verify and submit again.", t["key"])
            log(f"merge conflict on {t['key']} → back to {t['assignee']}")
            return
        self.b.update(t["key"], "lead", note=f"merged into {self.integration}", status="done")
        self.b.event(t["key"], "lead", "merge", f"merged {src} into {self.integration}")
        log(f"merged {t['key']} into {self.integration}")

    # ---------------------------------------------------------------- the loop
    def tick(self) -> None:
        self.escalated = set(self.b.meta().get("escalated", []))  # the human may resume one from the board
        for agent, (th, *_rest) in list(self.running.items()):
            if not th.is_alive():
                self.finished(agent)
        # 0. design: designer works, the human approves, the lead merges it so UI tasks can start
        for d in self.b.items(type_="design"):
            if d["key"] in self.escalated:
                continue
            busy = any(r[2] == d["key"] for r in self.running.values())
            if d["status"] in ("todo", "in_progress") and not busy and self.idle(self.designers):
                rounds = d.get("qa_rounds") or 0
                if rounds > self.d.get("max_rounds", 3):
                    self.escalate(d, f"design sent back {rounds} times")
                else:
                    self.start_design(d)
            elif d["status"] == "review" and not busy:
                verdict = d.get("qa_by") or ""
                if verdict.startswith("approved:"):
                    self.merge(d)
                elif self.d.get("approval") == "auto" or getattr(self.a, "auto_approve_design", False):
                    self.b.approve_design(d["key"], "auto-approved (team.design.approval = auto)", actor="lead")
                elif time.time() - self._waiting_note > 300:
                    self._waiting_note = time.time()
                    self.b.event(d["key"], "lead", "system", "waiting for the human to approve the design — "
                                 "open the board, view the mockup, then Approve or Request changes")
                    log(f"waiting for design approval on {d['key']}: {self.mockup_url('designer')}")
        tasks = self.tasks()
        # 1. merge QA-passed work
        for t in tasks:
            if t["status"] == "in_qa" and (t.get("qa_by") or "").startswith("pass:") and not any(
                    r[2] == t["key"] for r in self.running.values()):
                self.merge(t)
        tasks = self.tasks()
        # 2. QA picks up hand-offs
        for t in tasks:
            if t["status"] == "in_qa" and not t.get("qa_by"):
                free = self.idle(self.qas)
                if free:
                    self.start_qa(free[0], t)
        # 3. help blocked teammates
        for t in tasks:
            if t["status"] == "blocked" and t["key"] not in self.escalated and not any(
                    r[2] == t["key"] for r in self.running.values()):
                helpers = [n for n in self.idle(self.devs) if n != t["assignee"]] or \
                          [n for n in self.idle(self.qas)]
                if helpers:
                    self.start_help(helpers[0], t)
                elif len(self.devs) == 1 and not self.qas:
                    self.escalate(t, "no teammate available to help")
        # 4. developers: returning work first, then their own queue, then steal
        for dev in self.idle(self.devs):
            mine = [t for t in self.tasks() if t["assignee"] == dev and t["key"] not in self.escalated]
            back = [t for t in mine if t["status"] == "in_progress" and t.get("branch")
                    and not any(r[2] == t["key"] for r in self.running.values())]
            todo = [t for t in mine if t["status"] == "todo" and self.ready(t) and not self.file_clash(t)]
            if not back and not todo:
                todo = [t for t in self.tasks() if t["status"] == "todo" and self.ready(t) and not self.file_clash(t)
                        and not self.busy_owner_has(t)]
                if todo:
                    self.b.event(todo[0]["key"], "lead", "assign",
                                 f"reassigned from {todo[0]['assignee']} to {dev} (it was free)")
            pick = (back or todo or [None])[0]
            if pick:
                self.start_dev(dev, pick)
        if self.sync and time.time() - getattr(self, "_last_sync", 0) > self.t["sync_seconds"]:
            self._last_sync = time.time()
            self.sync.run()

    def busy_owner_has(self, t: dict) -> bool:
        """Don't steal a task its owner will reach soon — only steal when the owner is busy on something else."""
        return t["assignee"] in self.idle(self.devs)

    def done(self) -> bool:
        ts = self.tasks()
        return bool(ts) and all(t["status"] == "done" or t["key"] in self.escalated for t in ts) and not self.running

    def run(self) -> int:
        self.setup()
        signal.signal(signal.SIGINT, lambda *_: self.stop.set())
        signal.signal(signal.SIGTERM, lambda *_: self.stop.set())
        last_progress, last_state = time.time(), None
        while not self.stop.is_set():
            self.tick()
            state = json.dumps([(t["key"], t["status"], t.get("qa_by")) for t in self.b.items()
                                if t["type"] in ("task", "design")])
            if state != last_state or self.running:
                last_progress, last_state = time.time(), state
            if self.done():
                break
            waiting_human = any(d["status"] == "review" for d in self.b.items(type_="design"))
            if waiting_human and time.time() - last_progress < self.d.get("approval_timeout_minutes", 240) * 60:
                time.sleep(1 if self.a.simulate else self.t["poll_seconds"])
                continue
            if not self.running and time.time() - last_progress > 60:
                log("no progress possible — everything left is blocked or waiting on a human")
                break
            time.sleep(1 if self.a.simulate else self.t["poll_seconds"])
        for agent, (_, run, *_r) in list(self.running.items()):
            run.stop()
        for agent in list(getattr(self, "apps", {})):
            self.stop_app(agent)
        if self._design_srv:
            self._design_srv.shutdown()
        return self.wrap_up()

    def wrap_up(self) -> int:
        ts = self.tasks()
        done = [t for t in ts if t["status"] == "done"]
        iwt = self.wt("integration")
        verify_ok = None
        if done and not self.a.simulate and any(self.cfg["verify"].values()):
            r = sh([sys.executable, ".sdlc/bin/sdlc.py", "verify"], iwt, timeout=1800)
            verify_ok = r.returncode == 0
            self.b.event(None, "lead", "system", f"integration verify: {'PASS' if verify_ok else 'FAIL'}")
        agents = self.b.agents()
        report = [f"# Team report: {self.change.name}", "",
                  f"Integration branch: `{self.integration}` · finished {utcnow()}", "",
                  f"Tasks done: {len(done)}/{len(ts)} · escalated: {len(self.escalated)}"
                  + (f" · integration verify: {'PASS' if verify_ok else 'FAIL'}" if verify_ok is not None else ""), "",
                  "| Task | Title | Developer | QA | QA rounds | Status |", "|---|---|---|---|---|---|"]
        for t in ts:
            report.append(f"| {t['key']} | {t['title']} | {t['assignee'] or '-'} | {(t.get('qa_by') or '-').split(':')[-1]} "
                          f"| {t.get('qa_rounds') or 0} | {STATUS_LABEL.get(t['status'], t['status'])} |")
        report += ["", "| Agent | Role | Runs | Cost (est.) |", "|---|---|---|---|"]
        report += [f"| {a['name']} | {a['role']} | {a['runs']} | ${a['cost'] or 0:.2f} |" for a in agents]
        (iwt / self.rel).mkdir(parents=True, exist_ok=True)
        (iwt / self.rel / "team-report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
        sh("git add -A", iwt)
        sh(["git", "-c", "user.name=team-lead", "-c", "user.email=lead@sdlc.local", "commit", "-qm",
            f"team-report: {self.change.name}"], iwt)
        status = "done" if len(done) == len(ts) else "needs-human"
        self.b.set_meta(status=status, finished_at=utcnow())
        for a in agents:
            self.b.upsert_agent(a["name"], status="stopped", item_key=None)
        if self.sync:
            self.sync.run()
        log(f"team finished: {len(done)}/{len(ts)} tasks done, {len(self.escalated)} escalated → {self.integration}")
        if self.a.pr and status == "done" and not self.a.simulate:
            sh(["git", "push", "-u", "origin", self.integration], self.root)
            if shutil.which("gh"):
                sh(["gh", "pr", "create", "--head", self.integration, "--title", f"team: {self.change.name}",
                    "--body", f"Built by the agent team. See {self.rel}/team-report.md."], self.root)
        return 0 if status == "done" else 3


def cmd_run(root: Path, cfg: dict, a) -> None:
    change = resolve_change(root, cfg, a.change)
    b = Board()
    if not b.items(type_="task"):
        log("board is empty — planning first")
    cmd_plan(root, cfg, a)  # plans if needed; reloads an edited breakdown.json while no work has started
    if b.meta().get("change") != change.name:
        sys.exit(f"the board holds {b.meta().get('change')}; run team.py reset first")
    if not shutil.which("claude") and not a.simulate:
        sys.exit("claude CLI not on PATH")
    audit(root, "team-start", change=change.name)
    rc = Lead(root, cfg, change, a).run()
    audit(root, "team-end", change=change.name, rc=rc)
    sys.exit(rc)


def cmd_status(root: Path, cfg: dict, a) -> None:
    b = Board()
    m = b.meta()
    print(f"change {m.get('change')} · {m.get('status')} · tracker {m.get('tracker')} · branch {m.get('integration_branch')}")
    print_tree(b)
    print()
    for ag in b.agents():
        print(f"  {ag['name']:8} {ag['role'] or '':9} {ag['status'] or '':8} {ag['item_key'] or '-':5} "
              f"runs {ag['runs']} ${ag['cost'] or 0:.2f}  {ag['activity'] or ''}"[:160])


def cmd_reset(root: Path, cfg: dict, a) -> None:
    if os.environ.get("CLAUDECODE") or (not a.yes and not sys.stdin.isatty()):
        sys.exit("reset wipes the board; run it yourself in a terminal (or pass --yes)")
    Board().clear()  # in place: also works while the board server holds the file open (Windows)
    print("board cleared (worktrees and branches are kept; remove them with `git worktree remove`)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "run"):
        s = sub.add_parser(name)
        s.add_argument("change")
        s.add_argument("--developers", type=int)
        s.add_argument("--qa", type=int)
        s.add_argument("--simulate", action="store_true", help="scripted agents, no model calls (demo/test)")
        s.add_argument("--replan", action="store_true")
        s.add_argument("--pr", action="store_true")
        s.add_argument("--auto-approve-design", action="store_true", help="skip the human design gate (demos only)")
    sub.add_parser("status")
    s = sub.add_parser("reset"); s.add_argument("--yes", action="store_true")
    a = ap.parse_args()
    root = find_root()
    if not root:
        sys.exit("not an SDLC repo: run /sdlc:init first")
    cfg = load_config(root)
    {"plan": cmd_plan, "run": cmd_run, "status": cmd_status, "reset": cmd_reset}[a.cmd](root, cfg, a)


if __name__ == "__main__":
    main()
