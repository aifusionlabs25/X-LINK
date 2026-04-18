param(
    [string]$Url = "http://localhost:5001/hub/index.html?startup_home=1",
    [string]$RepoRoot = "C:\AI Fusion Labs\X AGENTS\REPOS\X-LINK",
    [int]$DebugPort = 9222,
    [int]$StartupTimeoutSeconds = 20
)

$ErrorActionPreference = "Stop"

function Test-CdpReady {
    param([int]$Port)

    try {
        $response = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/json/version" -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Test-BridgeReady {
    param([string]$TargetUrl)

    if ($TargetUrl -notmatch '^https?://(localhost|127\.0\.0\.1):5001/') {
        return $true
    }

    try {
        $response = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:5001/api/data" -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

$pythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python"
}

$browserCandidatePaths = @(@(
    "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    "C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
    "$env:LOCALAPPDATA\BraveSoftware\Brave-Browser\Application\brave.exe"
) | Where-Object { $_ -and (Test-Path $_) })

if (Test-CdpReady -Port $DebugPort) {
    if (Test-BridgeReady -TargetUrl $Url) {
        try {
            & $pythonExe (Join-Path $RepoRoot "tools\reveal_hub_safe.py") --url $Url | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Output "[OK] Reused the existing X-LINK browser session."
                exit 0
            }
        } catch {
            Write-Output "[WARN] Existing X-LINK browser session detected, but focus/reuse failed. Launching browser..."
        }
    } else {
        Write-Output "[INFO] Browser session exists, but the X-LINK bridge is not ready yet. Skipping Hub navigation for now."
        exit 0
    }
}

if ($browserCandidatePaths.Count -gt 0) {
    $browserExe = $browserCandidatePaths[0]
    Start-Process -FilePath $browserExe -ArgumentList @(
        "--new-window",
        "--remote-debugging-port=$DebugPort",
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank"
    ) | Out-Null

    for ($i = 0; $i -lt $StartupTimeoutSeconds; $i++) {
        if (Test-CdpReady -Port $DebugPort) {
            if (Test-BridgeReady -TargetUrl $Url) {
                try {
                    & $pythonExe (Join-Path $RepoRoot "tools\reveal_hub_safe.py") --url $Url | Out-Null
                    if ($LASTEXITCODE -eq 0) {
                        Write-Output "[OK] Opened or focused X-LINK in Brave with remote debugging on port $DebugPort."
                        exit 0
                    }
                } catch {
                    break
                }
            } else {
                Write-Output "[INFO] Browser is ready; waiting for the X-LINK bridge before opening the Hub."
                exit 0
            }
        }
        Start-Sleep -Seconds 1
    }

    Write-Output "[WARN] Brave launched, but CDP was not ready on port $DebugPort."
    exit 0
}

Write-Output "[ERROR] Brave was not found on this machine. No browser fallback was used."
exit 0
