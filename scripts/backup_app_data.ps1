param(
    [string]$DestinationRoot = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot "venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python virtual environment was not found: $python"
}

Push-Location $projectRoot
try {
    $arguments = @("-m", "app.asset_admin", "backup-all")
    if ($DestinationRoot) {
        $arguments += @("--destination-root", $DestinationRoot)
    }
    & $python @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Backup failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
