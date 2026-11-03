# One-command installer for the AI-Native SDLC Claude Code plugin (Windows PowerShell).
#   powershell -ExecutionPolicy Bypass -File install.ps1
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Scope project
# Note: the plugin's hooks run through bash, so Git for Windows (Git Bash) must be installed.
param([ValidateSet("user", "project", "local")][string]$Scope = "user")
$ErrorActionPreference = "Stop"

$Src = Split-Path -Parent $MyInvocation.MyCommand.Path
$Dest = if ($env:AI_NATIVE_SDLC_HOME) { $env:AI_NATIVE_SDLC_HOME } else { Join-Path $HOME ".ai-native-sdlc" }
$Market = "ai-native-sdlc"; $Plugin = "sdlc"

if (-not (Get-Command claude -ErrorAction SilentlyContinue)) { throw "Claude Code not found. Install it first: npm install -g @anthropic-ai/claude-code" }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Write-Warning "git not found - install Git for Windows (also provides bash for the hooks)" }
if (-not (Get-Command bash -ErrorAction SilentlyContinue)) { Write-Warning "bash not found - hooks will not run until Git Bash is installed" }
$py = Get-Command python3, python -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $py) { Write-Warning "Python 3.8+ not found - hooks will not enforce gates until it is installed" }
if (-not (Test-Path (Join-Path $Src ".claude-plugin\marketplace.json"))) { throw "Run this from the unzipped ai-native-sdlc-kit folder" }

if ((Resolve-Path $Src).Path -ne $Dest) {
  Write-Host "==> Copying kit to $Dest"
  if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }
  New-Item -ItemType Directory -Force $Dest | Out-Null
  Get-ChildItem -Force $Src | Where-Object { $_.Name -ne ".git" } | Copy-Item -Destination $Dest -Recurse -Force
}

$list = (& claude plugin marketplace list 2>$null) -join "`n"
if ($list -match $Market) { & claude plugin marketplace remove $Market 2>$null | Out-Null }
Write-Host "==> Adding marketplace from $Dest"
& claude plugin marketplace add $Dest --scope $Scope
Write-Host "==> Installing $Plugin@$Market (scope: $Scope)"
& claude plugin install "$Plugin@$Market" --scope $Scope

Write-Host ""
Write-Host "Next:"
Write-Host "  1. Sign in once:      claude auth login   (Claude Pro/Max/Team) - or ANTHROPIC_API_KEY / Bedrock vars"
Write-Host "  2. Open your app:     mkdir my-app; cd my-app; claude"
Write-Host "  3. Inside Claude:     /sdlc:loop <your idea>"
