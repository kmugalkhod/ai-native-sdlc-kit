# AI-Native SDLC kit — instructions for Claude

This folder is a Claude Code plugin marketplace (`ai-native-sdlc`) containing one plugin (`sdlc`).

## When the user asks you to install it
Run exactly one command from this folder:
- Linux / macOS / Git Bash: `bash install.sh`
- Windows PowerShell: `powershell -ExecutionPolicy Bypass -File install.ps1`

Add `--scope project` (bash) or `-Scope project` (PowerShell) only if the user wants it for one project instead of all of them.
The installer checks prerequisites, copies the kit to `~/.ai-native-sdlc`, adds the marketplace and installs `sdlc@ai-native-sdlc`. It is safe to re-run; re-running updates the plugin.

After it finishes, tell the user to:
1. Restart Claude Code so the `/sdlc:*` commands appear.
2. Sign in with `claude auth login` (Claude subscription), or set `ANTHROPIC_API_KEY` / the Bedrock variables.
3. Open their app repo and run `/sdlc:init`, then `/sdlc:intent <idea>`.

If `claude` is not on PATH, the installer stops and says so. Ask the user to install Claude Code first rather than working around it.

## When the user asks to uninstall
`claude plugin uninstall sdlc@ai-native-sdlc && claude plugin marketplace remove ai-native-sdlc`

## Editing the kit
Plugin code lives in `plugins/sdlc/`. After changing it, run `claude plugin validate ./plugins/sdlc`, then `bash install.sh` to pick up the changes. See README.md for the architecture.
