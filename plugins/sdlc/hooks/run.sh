#!/usr/bin/env bash
# Thin launcher: finds a Python 3 interpreter (python3 on Linux/macOS, python on Windows Git Bash)
# and runs the hook. If no Python is found the hook fails open with a warning on stderr.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for PY in python3 python; do
  if command -v "$PY" >/dev/null 2>&1 && "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
    exec "$PY" "$HERE/../scripts/sdlc_hooks.py" "$@"
  fi
done
echo "sdlc hooks: no Python 3.8+ found; gates are NOT enforced" >&2
exit 0
