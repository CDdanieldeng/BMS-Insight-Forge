# Run Insight Forge backend locally
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $ProjectRoot "backend"
$EnvFile = Join-Path $ProjectRoot ".env"

# Load .env into current PowerShell process
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $parts = $line.Split("=", 2)
        if ($parts.Count -eq 2) {
            [System.Environment]::SetEnvironmentVariable($parts[0], $parts[1], "Process")
        }
    }
}

# Ensure local calls bypass any global HTTP proxy
if ([string]::IsNullOrWhiteSpace($env:NO_PROXY)) {
    $env:NO_PROXY = "localhost,127.0.0.1"
} elseif ($env:NO_PROXY -notmatch "localhost") {
    $env:NO_PROXY = "$($env:NO_PROXY),localhost,127.0.0.1"
}

$env:PYTHONPATH = $BackendDir
Set-Location $BackendDir
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8001
