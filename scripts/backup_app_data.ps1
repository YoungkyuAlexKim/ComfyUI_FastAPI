[CmdletBinding()]
param(
    [string]$DestinationRoot = "",
    [ValidateRange(0, 3650)]
    [int]$RetentionDays = 0,
    [ValidateRange(0, 1000)]
    [int]$MinimumBundles = 7,
    [string]$LogDirectory = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot "venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python virtual environment was not found: $python"
}

if ([string]::IsNullOrWhiteSpace($DestinationRoot)) {
    $DestinationRoot = Join-Path $projectRoot "backups"
    Write-Warning "No destination was supplied; using the project-local development backup directory."
}
$destination = [System.IO.Path]::GetFullPath($DestinationRoot)

if ([string]::IsNullOrWhiteSpace($LogDirectory)) {
    $LogDirectory = Join-Path $projectRoot "logs\backup"
}
$logRoot = [System.IO.Path]::GetFullPath($LogDirectory)
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$logPath = Join-Path $logRoot "backup-$stamp.log"

$hash = [System.Security.Cryptography.SHA256]::Create()
try {
    $destinationBytes = [System.Text.Encoding]::UTF8.GetBytes($destination.ToLowerInvariant())
    $mutexSuffix = ([System.BitConverter]::ToString($hash.ComputeHash($destinationBytes))).Replace("-", "").Substring(0, 16)
}
finally {
    $hash.Dispose()
}
$mutex = New-Object System.Threading.Mutex($false, "Local\LC_AI_Canvas_Backup_$mutexSuffix")
$lockTaken = $false

function Invoke-LoggedPython {
    param([string[]]$Arguments)
    & $python @Arguments 2>&1 | Tee-Object -FilePath $logPath -Append
    if ($LASTEXITCODE -ne 0) {
        throw "Backup command failed with exit code $LASTEXITCODE. See $logPath"
    }
}

try {
    $lockTaken = $mutex.WaitOne(0)
    if (-not $lockTaken) {
        throw "Another backup for this destination is already running: $destination"
    }

    Push-Location $projectRoot
    try {
        "[$([DateTime]::UtcNow.ToString('o'))] backup start: $destination" | Tee-Object -FilePath $logPath -Append
        Invoke-LoggedPython @("-m", "app.asset_admin", "backup-all", "--destination-root", $destination)
        if ($RetentionDays -gt 0) {
            Invoke-LoggedPython @(
                "-m", "app.asset_admin", "prune-backups", $destination,
                "--retention-days", [string]$RetentionDays,
                "--minimum-bundles", [string]$MinimumBundles,
                "--apply"
            )
        }
        "[$([DateTime]::UtcNow.ToString('o'))] backup complete" | Tee-Object -FilePath $logPath -Append
    }
    finally {
        Pop-Location
    }
}
finally {
    if ($lockTaken) {
        $mutex.ReleaseMutex()
    }
    $mutex.Dispose()
}
