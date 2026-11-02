# Install

Unzip, then run one command inside the `ai-native-sdlc-kit` folder:

| OS | Command |
|---|---|
| Linux / macOS / Windows Git Bash | `bash install.sh` |
| Windows PowerShell | `powershell -ExecutionPolicy Bypass -File install.ps1` |

Or open Claude Code in this folder and say **"install this plugin"**; `CLAUDE.md` tells Claude what to run.

The installer:
1. Checks for Claude Code, git and Python 3.8+.
2. Copies the kit to `~/.ai-native-sdlc`, so deleting the download is safe.
3. Adds the `ai-native-sdlc` marketplace and installs `sdlc@ai-native-sdlc`.

Re-running it updates the plugin.

## Then
```bash
claude auth login          # Claude subscription (or set ANTHROPIC_API_KEY / Bedrock vars)
cd <your-app-repo> && claude
```
Inside Claude, run `/sdlc:init`, then `/sdlc:intent <your idea>`. The full loop is described in README.md.

## Uninstall
```bash
claude plugin uninstall sdlc@ai-native-sdlc && claude plugin marketplace remove ai-native-sdlc
```
