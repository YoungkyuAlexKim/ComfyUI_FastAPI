[CmdletBinding()]
param(
    [ValidateSet("Development", "Production")]
    [string]$Mode = "Development",
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,
    [switch]$NoBrowser,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot "venv\Scripts\python.exe"
$healthUrl = "http://127.0.0.1:$Port/healthz"
$pageUrl = "http://127.0.0.1:$Port/create"

function Get-HealthyExistingServer {
    try {
        $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3
        return ($null -ne $health -and $health.ok -eq $true)
    }
    catch {
        return $false
    }
}

function Get-PortListeners {
    try {
        return @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop)
    }
    catch {
        return @()
    }
}

if (Get-HealthyExistingServer) {
    Write-Host "[OK] LC AI Canvas is already healthy on port $Port."
    Write-Host "[INFO] $pageUrl"
    if ($Mode -eq "Development" -and -not $NoBrowser -and -not $CheckOnly) {
        Start-Process $pageUrl
    }
    exit 0
}

$listeners = @(Get-PortListeners)
if ($listeners.Count -gt 0) {
    $processIds = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique) -join ", "
    Write-Host "[ERROR] Port $Port is occupied but LC AI Canvas health failed. Owning PID(s): $processIds" -ForegroundColor Red
    exit 2
}

if ($CheckOnly) {
    Write-Host "[OK] Port $Port is available and no existing server was detected."
    exit 0
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    Write-Host "[ERROR] Python virtual environment was not found: $python" -ForegroundColor Red
    exit 3
}

$logRoot = Join-Path $projectRoot "logs"
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$modeLabel = $Mode.ToLowerInvariant()
$logPath = Join-Path $logRoot "server-$modeLabel-$stamp.log"

$uvicornArguments = @(
    "-m", "uvicorn", "app.main:app",
    "--port", [string]$Port,
    "--no-proxy-headers"
)
if ($Mode -eq "Development") {
    $uvicornArguments += @("--reload", "--host", "127.0.0.1")
}
else {
    $uvicornArguments += @("--host", "0.0.0.0")
}

if ($Mode -eq "Development" -and -not $NoBrowser) {
    Start-Job -ScriptBlock {
        param($HealthUrl, $PageUrl)
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            try {
                $health = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 2
                if ($health.ok -eq $true) {
                    Start-Process $PageUrl
                    return
                }
            }
            catch {
            }
            Start-Sleep -Milliseconds 500
        }
    } -ArgumentList $healthUrl, $pageUrl | Out-Null
}

Write-Host "[INFO] Starting LC AI Canvas in $Mode mode."
Write-Host "[INFO] Log: $logPath"
Push-Location $projectRoot
try {
    # Uvicorn writes normal lifecycle logs to stderr. Windows PowerShell 5.1
    # turns redirected native stderr into ErrorRecord objects, which pollutes
    # logs and can trip strict error handling. Merge streams in cmd.exe first
    # so PowerShell receives plain text and then trust the native exit code.
    $quotedPython = '"' + $python.Replace('"', '\"') + '"'
    $quotedArguments = @(
        $uvicornArguments | ForEach-Object { '"' + ([string]$_).Replace('"', '\"') + '"' }
    )
    $nativeCommand = $quotedPython + " " + ($quotedArguments -join " ") + " 2>&1"
    & $env:ComSpec /d /s /c $nativeCommand | Tee-Object -FilePath $logPath -Append
    $serverExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($serverExitCode -ne 0) {
    Write-Host "[ERROR] Uvicorn exited with code $serverExitCode. See $logPath" -ForegroundColor Red
    exit $serverExitCode
}
exit 0
