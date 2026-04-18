param(
    [string]$Distro = "Ubuntu",
    [string]$RepoRoot = "C:\AI Fusion Labs\X AGENTS\REPOS\X-LINK"
)

$ErrorActionPreference = "Stop"

$linuxRepoRoot = "/mnt/" + $RepoRoot.Substring(0,1).ToLower() + $RepoRoot.Substring(2).Replace("\","/")
$bashCommand = "if pgrep -af ""hermes gateway"" >/dev/null; then pkill -f ""hermes gateway""; echo stopped; else echo not-running; fi"

& wsl -d $Distro -- bash -lc $bashCommand
