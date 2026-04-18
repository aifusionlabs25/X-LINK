param(
    [string]$Distro = "Ubuntu",
    [string]$ApiUrl = "http://127.0.0.1:8642/v1/models",
    [string]$ApiKey = "xlink-local-key",
    [int]$StartupTimeoutSeconds = 25,
    [string]$RepoRoot = "C:\AI Fusion Labs\X AGENTS\REPOS\X-LINK"
)

$ErrorActionPreference = "Stop"

function Test-HermesApi {
    param(
        [string]$Url,
        [string]$Key
    )

    try {
        $response = Invoke-WebRequest -UseBasicParsing $Url -Headers @{ Authorization = "Bearer $Key" } -TimeoutSec 3
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

if (Test-HermesApi -Url $ApiUrl -Key $ApiKey) {
    Write-Output "[OK] Hermes API is already online."
    exit 0
}

$gatewayCommand = 'source ~/.local/bin/env >/dev/null 2>&1 || true; exec hermes gateway'

try {
    $argumentString = "-d $Distro -- bash -lc ""$gatewayCommand"""
    Start-Process -FilePath "wsl.exe" -ArgumentList $argumentString -WindowStyle Minimized | Out-Null
    Write-Output "started"
} catch {
    Write-Error "Failed to start Hermes gateway in WSL."
    Write-Error $_.Exception.Message
    exit 1
}

for ($i = 0; $i -lt $StartupTimeoutSeconds; $i++) {
    if (Test-HermesApi -Url $ApiUrl -Key $ApiKey) {
        Write-Output "[OK] Hermes API is online at $ApiUrl"
        exit 0
    }
    Start-Sleep -Seconds 1
}

Write-Error "Hermes API did not come online within $StartupTimeoutSeconds seconds. Check ~/.hermes/logs/gateway.log in Ubuntu."
exit 1
