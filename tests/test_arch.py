"""Architecture step: the Mermaid → draw.io export is faithful, and nothing is planned against an architecture a
human has not approved (headless pipeline escalates, team prepare waits for the human). python tests/test_arch.py
"""
import subprocess
import sys
import tempfile
import xml.dom.minidom as minidom
from pathlib import Path

KIT = Path(__file__).resolve().parents[1] / "plugins" / "sdlc"
S = KIT / "scripts"
sys.path.insert(0, str(S))
from sdlc_core import architecture_problem  # noqa: E402

DIAGRAM = """# Architecture

Status: proposed

```mermaid
flowchart LR
  app((Your LLM app)) -- "SDK batches" --> api
  otel((OTel exporter)) -->|OTLP/HTTP| api
  subgraph svc [Server]
    api[Ingestion API] --> q[/Event queue/]
    q --> worker[Worker]
    ui(Web UI) & papi[Public API] --> db
    subgraph jobs [Background]
      judge{{LLM judge}}
    end
  end
  worker ==> db[(Postgres)]
  worker -.-> judge -.-> llm((LLM provider))
  judge --- db
  classDef x fill:#fff
```
"""
fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += not ok
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail and not ok else ""))


def run(*args, cwd):
    return subprocess.run([sys.executable, *map(str, args)], cwd=cwd, capture_output=True, text=True)


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="sdlc-arch-"))
    for c in (["git", "init", "-q", "-b", "main"], ["git", "config", "user.email", "t@x"],
              ["git", "config", "user.name", "t"]):
        subprocess.run(c, cwd=root)
    run(S / "init.py", "--root", root, cwd=root)
    (root / "sdlc").mkdir(exist_ok=True)
    arch = root / "sdlc" / "ARCHITECTURE.md"

    # 1. export, with each layout engine available here (Graphviz when installed, and the built-in one)
    arch.write_text(DIAGRAM, encoding="utf-8")
    import shutil
    for layout in (["dot"] if shutil.which("dot") else []) + ["builtin"]:
        export(root, arch, layout)
    approval(root, arch)


def export(root, arch, layout):
    r = run(root / ".sdlc" / "bin" / "arch_export.py", "--no-png", "--layout", layout, cwd=root)
    check(f"[{layout}] export runs from the installed bin", r.returncode == 0, r.stdout + r.stderr)
    f = root / "sdlc" / "architecture.drawio"
    svg = root / "sdlc" / "architecture.svg"
    check(f"[{layout}] SVG picture written, with title and legend", svg.is_file()
          and "architecture" in svg.read_text(encoding="utf-8").lower() and "Data store" in svg.read_text(encoding="utf-8"))
    cells = minidom.parse(str(f)).getElementsByTagName("mxCell") if f.is_file() else []
    rel = {c.getAttribute("id"): ([float(c.getElementsByTagName("mxGeometry")[0].getAttribute(k))
                                   for k in ("x", "y", "width", "height")], c.getAttribute("parent"))
           for c in cells if c.getAttribute("vertex") == "1"}

    def absolute(i):  # draw.io groups are containers: children are placed relative to their group
        (x, y, w, h), par = rel[i]
        if par in rel:
            px, py, _, _ = absolute(par)
            return [x + px, y + py, w, h]
        return [x, y, w, h]

    geo = {i: absolute(i) for i in rel}
    nodes = {k for k in geo if k.startswith("n_")}
    edges = [c for c in cells if c.getAttribute("edge") == "1"]
    check(f"[{layout}] " + "all 10 nodes and 10 edges", len(nodes) == 10 and len(edges) == 10, f"{len(nodes)} nodes {len(edges)} edges")
    labels = {c.getAttribute("value") for c in cells}
    check(f"[{layout}] " + "labels kept (node, store, edge text)", {"Ingestion API", "Postgres", "SDK batches", "OTLP/HTTP"} <= labels)
    styles = {c.getAttribute("id"): c.getAttribute("style") for c in cells}
    check(f"[{layout}] " + "store drawn as a cylinder, queue as a parallelogram",
          "cylinder" in styles.get("n_db", "") and "parallelogram" in styles.get("n_q", ""))
    check(f"[{layout}] " + "dashed, thick and undirected edges kept", any("endArrow=none" in c.getAttribute("style") for c in edges)
          and any("dashed=1" in c.getAttribute("style") for c in edges)
          and any("strokeWidth=3" in c.getAttribute("style") for c in edges))
    inside = lambda n, g: (geo[g][0] <= geo[n][0] and geo[n][0] + geo[n][2] <= geo[g][0] + geo[g][2]
                           and geo[g][1] <= geo[n][1] and geo[n][1] + geo[n][3] <= geo[g][1] + geo[g][3])
    in_svc = {n for n in nodes if inside(n, "grp_svc")}
    check(f"[{layout}] " + "subgraph box holds exactly its members (api moved in, like Mermaid)",
          in_svc == {"n_api", "n_q", "n_worker", "n_ui", "n_papi", "n_db", "n_judge"}, str(sorted(in_svc)))
    check(f"[{layout}] " + "nested subgraph", {n for n in nodes if inside(n, "grp_jobs")} == {"n_judge"})
    overlap = [(a, b) for a in nodes for b in nodes if a < b and not (
        geo[a][0] + geo[a][2] <= geo[b][0] or geo[b][0] + geo[b][2] <= geo[a][0]
        or geo[a][1] + geo[a][3] <= geo[b][1] or geo[b][1] + geo[b][3] <= geo[a][1])]
    check(f"[{layout}] " + "no two nodes overlap", not overlap, str(overlap))
    bad = root / "bad.md"
    bad.write_text("```mermaid\nflowchart LR\n  a --> b ??? c\n```\n", encoding="utf-8")
    r = run(S / "arch_export.py", bad, "--no-png", cwd=root)
    check(f"[{layout}] " + "unsupported syntax is reported, not guessed", r.returncode == 2 and "line 2" in r.stdout, r.stdout)



def approval(root, arch):
    check("proposed architecture blocks planning", bool(architecture_problem(root)))
    subprocess.run([sys.executable, str(root / ".sdlc/bin/sdlc.py"), "new", "trace-app"], cwd=root,
                   capture_output=True)
    change = next((root / "sdlc" / "changes").glob("*trace-app*"))
    (change / "intent.md").write_text("# Intent\n\nStatus: accepted\n\nBuild a trace app.\n", encoding="utf-8")
    (change / "spec.md").write_text("# Spec\n\nStatus: accepted\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root)
    subprocess.run(["git", "commit", "-qm", "setup"], cwd=root)
    env_fake = {"SDLC_CLAUDE_CMD": f'["{sys.executable}", "-c", "print(1)"]'}
    import os
    r = subprocess.run([sys.executable, str(root / ".sdlc/bin/pipeline.py"), "trace-app", "--from", "plan",
                        "--to", "plan", "--no-commit"], cwd=root, capture_output=True, text=True,
                       env={**os.environ, **env_fake})
    esc = change / "ESCALATION.md"
    check("headless pipeline escalates before planning", r.returncode == 3 and esc.is_file()
          and "ARCHITECTURE.md" in esc.read_text(encoding="utf-8"), r.stdout[-400:] + r.stderr[-400:])
    r = subprocess.run([sys.executable, str(root / ".sdlc/bin/team.py"), "prepare", "trace-app"], cwd=root,
                       capture_output=True, text=True, env={**os.environ, **env_fake})
    plan_made = (change / "breakdown.json").exists()
    check("team prepare waits for the human, plans nothing", r.returncode == 0 and '"architecture approval"' in r.stdout
          and not plan_made, r.stdout[-300:] + r.stderr[-300:])
    arch.write_text(DIAGRAM.replace("Status: proposed", "Status: approved\nApproved by: t"), encoding="utf-8")
    check("approved architecture lets planning run", architecture_problem(root) is None)
    arch.unlink()
    check("no architecture file: nothing to wait for", architecture_problem(root) is None)


def finish():
    print("ALL PASS" if not fails else f"{fails} FAILED")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
    finish()
