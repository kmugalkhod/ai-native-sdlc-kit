"""The shell guard blocks writes INTO the kit's governance files, and only those.
A redirect of a kit script's output to a log elsewhere is fine (it used to be blocked). python tests/test_hooks_shell.py
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[1] / "plugins" / "sdlc"
H = KIT / "scripts" / "sdlc_hooks.py"
G = ".sdlc/"  # spelled in pieces so this file itself never looks like a governance write
CASES = [
    (f"nohup python3 {G}bin/board_server.py --port 8799 > /tmp/b.log 2>&1 &", 0),
    (f"(nohup python3 {G}bin/board_server.py > /tmp/b.log 2>&1 &)", 0),
    (f"python3 {G}bin/team.py run x > /tmp/run.log 2>&1", 0),
    (f"cat {G}state/loop.json > /tmp/x.json", 0),
    (f"cp {G}config.json /tmp/backup.json", 0),
    (f"echo '{{}}' > {G}config.json", 2),
    (f"python3 {G}bin/board.py show > {G}state/x.txt", 2),
    (f"cp evil.py {G}bin/team.py", 2),
    (f"rm -f {G}audit.jsonl", 2),
    (f"sed -i s/a/b/ {G}config.json", 2),
    (f"tee {G}state/board.db < x", 2),
]


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="sdlc-hk-"))
    subprocess.run(["git", "init", "-q"], cwd=root)
    subprocess.run([sys.executable, str(KIT / "scripts" / "init.py"), "--root", str(root)], cwd=root,
                   capture_output=True)
    bad = 0
    for cmd, want in CASES:
        r = subprocess.run([sys.executable, str(H), "pre-bash"], capture_output=True, text=True,
                           input=json.dumps({"cwd": str(root), "tool_name": "Bash", "tool_input": {"command": cmd}}))
        ok = r.returncode == want
        bad += not ok
        print(("PASS " if ok else "FAIL ") + ("blocked  " if want else "allowed  ") + cmd)
    print("ALL PASS" if not bad else f"{bad} FAILED")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
