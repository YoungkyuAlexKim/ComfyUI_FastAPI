[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BackupPath
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python virtual environment was not found: $python"
}

Push-Location $projectRoot
try {
    & $python -m app.asset_admin restore-drill ([System.IO.Path]::GetFullPath($BackupPath))
    if ($LASTEXITCODE -ne 0) {
        throw "Restore drill failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
