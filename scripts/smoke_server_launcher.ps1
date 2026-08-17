[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 49153
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$launcherPath = Join-Path $PSScriptRoot "start_server.ps1"
$tempBase = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$probeRoot = Join-Path $tempBase ("lc-canvas-launcher-" + [guid]::NewGuid().ToString("N"))
$launcher = $null
$listenerProcessId = $null

if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Probe port $Port is already in use."
}

New-Item -ItemType Directory -Path $probeRoot -Force | Out-Null
try {
    $probeDb = Join-Path $probeRoot "probe.db"
    $probeOutput = Join-Path $probeRoot "outputs"
    $stdoutPath = Join-Path $probeRoot "launcher.stdout.log"
    $stderrPath = Join-Path $probeRoot "launcher.stderr.log"
    New-Item -ItemType Directory -Path $probeOutput -Force | Out-Null

    $appLogPath = Join-Path $projectRoot "logs\app.log"
    $beforeLength = -1
    $beforeWrite = $null
    if (Test-Path -LiteralPath $appLogPath) {
        $appLog = Get-Item -LiteralPath $appLogPath
        $beforeLength = $appLog.Length
        $beforeWrite = $appLog.LastWriteTimeUtc
    }

    $environmentNames = @(
        "JOB_DB_PATH",
        "OUTPUT_DIR",
        "PRINCIPAL_COOKIE_SECRET",
        "BETA_PASSWORD",
        "LOG_TO_FILE",
        "ASSET_CATALOG_FALLBACK_ENABLED"
    )
    $previousEnvironment = @{}
    foreach ($name in $environmentNames) {
        $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    }
    try {
        $env:JOB_DB_PATH = $probeDb
        $env:OUTPUT_DIR = $probeOutput
        $env:PRINCIPAL_COOKIE_SECRET = "launcher-probe-" + ("x" * 48)
        $env:BETA_PASSWORD = ""
        $env:LOG_TO_FILE = "true"
        $env:ASSET_CATALOG_FALLBACK_ENABLED = "false"
        $launcher = Start-Process `
            -FilePath "powershell.exe" `
            -ArgumentList @(
                "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $launcherPath,
                "-Mode", "Production", "-Port", [string]$Port, "-NoBrowser"
            ) `
            -WorkingDirectory $projectRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput $stdoutPath `
            -RedirectStandardError $stderrPath `
            -PassThru
    }
    finally {
        foreach ($name in $environmentNames) {
            [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process")
        }
    }

    $listener = $null
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($listener -or $launcher.HasExited) {
            break
        }
        Start-Sleep -Milliseconds 200
    }
    if (-not $listener) {
        $stdout = if (Test-Path -LiteralPath $stdoutPath) { Get-Content -LiteralPath $stdoutPath -Raw } else { "" }
        $stderr = if (Test-Path -LiteralPath $stderrPath) { Get-Content -LiteralPath $stderrPath -Raw } else { "" }
        throw "Probe server did not listen. stdout=$stdout stderr=$stderr"
    }

    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/healthz" -TimeoutSec 10
    $listenerProcessId = [int]$listener.OwningProcess
    $listenerProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$listenerProcessId"
    $portPattern = "--port[^`r`n]{0,12}$Port"
    if (
        $listenerProcess.CommandLine -notmatch "uvicorn.*app\.main:app" -or
        $listenerProcess.CommandLine -notmatch $portPattern
    ) {
        throw "Unexpected listener process $listenerProcessId."
    }

    Stop-Process -Id $listenerProcessId -Force
    $listenerProcessId = $null
    if (-not $launcher.WaitForExit(15000)) {
        throw "Launcher did not exit after its supervised server stopped."
    }
    Start-Sleep -Milliseconds 400

    $leftovers = @(
        Get-CimInstance Win32_Process |
            Where-Object {
                $_.CommandLine -match "uvicorn.*app\.main:app" -and
                $_.CommandLine -match $portPattern
            }
    )
    $stdout = if (Test-Path -LiteralPath $stdoutPath) { Get-Content -LiteralPath $stdoutPath -Raw } else { "" }
    $stderr = if (Test-Path -LiteralPath $stderrPath) { Get-Content -LiteralPath $stderrPath -Raw } else { "" }
    $combined = $stdout + "`n" + $stderr
    $afterLength = -1
    $afterWrite = $null
    if (Test-Path -LiteralPath $appLogPath) {
        $appLog = Get-Item -LiteralPath $appLogPath
        $afterLength = $appLog.Length
        $afterWrite = $appLog.LastWriteTimeUtc
    }
    $lockPath = Join-Path $projectRoot "logs\server-$Port.lock"
    $result = [ordered]@{
        launcher_exited = $launcher.HasExited
        health_ok = ($health.ok -eq $true)
        startup_complete = ($combined -match "Application startup complete")
        logging_error = ($combined -match "Logging error|WinError 32")
        shared_app_log_unchanged = ($beforeLength -eq $afterLength -and $beforeWrite -eq $afterWrite)
        leftover_processes = $leftovers.Count
        lock_present = (Test-Path -LiteralPath $lockPath)
    }
    $result | ConvertTo-Json -Compress

    if (
        -not $result.launcher_exited -or
        -not $result.health_ok -or
        -not $result.startup_complete -or
        $result.logging_error -or
        -not $result.shared_app_log_unchanged -or
        $result.leftover_processes -ne 0 -or
        $result.lock_present
    ) {
        throw "Launcher smoke verification failed."
    }
}
finally {
    if ($null -ne $listenerProcessId) {
        Stop-Process -Id $listenerProcessId -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $launcher -and -not $launcher.HasExited) {
        Stop-Process -Id $launcher.Id -Force -ErrorAction SilentlyContinue
    }
    $resolvedProbe = [System.IO.Path]::GetFullPath($probeRoot)
    if (-not $resolvedProbe.StartsWith($tempBase, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a probe directory outside the system temp directory."
    }
    if (Test-Path -LiteralPath $resolvedProbe) {
        Remove-Item -LiteralPath $resolvedProbe -Recurse -Force
    }
}
