#!/usr/bin/env bash
# One-command installer for the AI-Native SDLC Claude Code plugin.
#   bash install.sh                 # install for your user (all repos)
#   bash install.sh --scope project # install only for the current project
# Works on Linux, macOS and Windows Git Bash. Safe to re-run (updates in place).
set -euo pipefail

SCOPE="user"
while [ $# -gt 0 ]; do
  case "$1" in
    --scope) SCOPE="${2:-user}"; shift 2 ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
done

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${AI_NATIVE_SDLC_HOME:-$HOME/.ai-native-sdlc}"
MARKET="ai-native-sdlc"
PLUGIN="sdlc"

say()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarn:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# 1. prerequisites
command -v claude >/dev/null 2>&1 || die "Claude Code not found. Install it first: https://code.claude.com/docs (npm install -g @anthropic-ai/claude-code)"
command -v git >/dev/null 2>&1 || warn "git not found — the SDLC loop needs git in your project repos"
PY=""
for p in python3 python; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then PY="$p"; break; fi
done
[ -n "$PY" ] || warn "Python 3.8+ not found — hooks will not enforce gates until it is installed"
[ -f "$SRC/.claude-plugin/marketplace.json" ] || die "run this from the unzipped ai-native-sdlc-kit folder (marketplace.json not found)"

# 2. copy to a stable location so deleting the download doesn't break the plugin
if [ "$SRC" != "$DEST" ]; then
  say "Copying kit to $DEST"
  rm -rf "$DEST.tmp" && mkdir -p "$DEST.tmp"
  (cd "$SRC" && tar --exclude=.git --exclude=__pycache__ -cf - .) | (cd "$DEST.tmp" && tar -xf -)
  rm -rf "$DEST" && mv "$DEST.tmp" "$DEST"
fi
chmod +x "$DEST"/plugins/sdlc/hooks/*.sh "$DEST"/plugins/sdlc/scripts/*.py 2>/dev/null || true

# 3. register marketplace + install (or update) the plugin
if claude plugin marketplace list 2>/dev/null | grep -q "$MARKET"; then
  say "Updating marketplace $MARKET"
  claude plugin marketplace remove "$MARKET" >/dev/null 2>&1 || true
fi
say "Adding marketplace from $DEST"
claude plugin marketplace add "$DEST" --scope "$SCOPE"
say "Installing $PLUGIN@$MARKET (scope: $SCOPE)"
claude plugin install "$PLUGIN@$MARKET" --scope "$SCOPE"

# 4. verify
if claude plugin list 2>/dev/null | grep -q "$PLUGIN@$MARKET"; then
  say "Installed."
else
  warn "Install finished but the plugin isn't listed — run: claude plugin list"
fi

cat <<'EOF'

Next:
  1. Sign in once:      claude auth login      (Claude Pro/Max/Team)  — or set ANTHROPIC_API_KEY / Bedrock vars
  2. Open your app:     mkdir my-app && cd my-app && claude
  3. Inside Claude:     /sdlc:loop <your idea>

Uninstall:  claude plugin uninstall sdlc@ai-native-sdlc && claude plugin marketplace remove ai-native-sdlc
EOF
