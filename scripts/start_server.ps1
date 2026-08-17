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

function Get-DescendantProcessIds {
    param([int]$RootProcessId)

    $allProcesses = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $pending = New-Object System.Collections.Generic.Queue[int]
    $pending.Enqueue($RootProcessId)
    $descendants = New-Object System.Collections.Generic.List[int]
    while ($pending.Count -gt 0) {
        $parentId = $pending.Dequeue()
        foreach ($child in @($allProcesses | Where-Object { [int]$_.ParentProcessId -eq $parentId })) {
            $childId = [int]$child.ProcessId
            if (-not $descendants.Contains($childId)) {
                $descendants.Add($childId)
                $pending.Enqueue($childId)
            }
        }
    }
    return @($descendants)
}

function Stop-LauncherProcessTree {
    param([int]$RootProcessId)

    $targets = @(Get-DescendantProcessIds -RootProcessId $RootProcessId)
    [array]::Reverse($targets)
    foreach ($targetId in $targets) {
        Stop-Process -Id $targetId -Force -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $RootProcessId -Force -ErrorAction SilentlyContinue
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
$launcherLockPath = Join-Path $logRoot "server-$Port.lock"
$launcherLock = $null
try {
    $launcherLock = [System.IO.FileStream]::new(
        $launcherLockPath,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None,
        1,
        [System.IO.FileOptions]::DeleteOnClose
    )
    $lockText = [System.Text.Encoding]::UTF8.GetBytes("launcher_pid=$PID`n")
    $launcherLock.SetLength(0)
    $launcherLock.Write($lockText, 0, $lockText.Length)
    $launcherLock.Flush()
}
catch {
    Write-Host "[ERROR] Another LC AI Canvas launcher is already starting or supervising port $Port." -ForegroundColor Red
    exit 4
}

# Close the health/port race between the first check and launcher-lock acquisition.
if (Get-HealthyExistingServer) {
    Write-Host "[OK] LC AI Canvas became healthy on port $Port while this launcher was waiting."
    $launcherLock.Dispose()
    exit 0
}
$listeners = @(Get-PortListeners)
if ($listeners.Count -gt 0) {
    $processIds = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique) -join ", "
    Write-Host "[ERROR] Port $Port became occupied while starting. Owning PID(s): $processIds" -ForegroundColor Red
    $launcherLock.Dispose()
    exit 2
}

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
$serverProcess = $null
$logWriter = $null
$serverExitCode = 1
$previousLogToFile = [Environment]::GetEnvironmentVariable("LOG_TO_FILE", "Process")
Push-Location $projectRoot
try {
    # The launcher already captures every application and Uvicorn line in a
    # unique server log. Disable the duplicate shared app.log handler for this
    # child process so a stale helper cannot block Windows file rotation.
    [Environment]::SetEnvironmentVariable("LOG_TO_FILE", "false", "Process")

    # Uvicorn writes lifecycle logs to stderr. Merge its streams in cmd.exe,
    # then supervise that exact process tree so Ctrl+C or launcher failure does
    # not leave a detached LC AI Canvas Python process behind.
    $quotedPython = '"' + $python.Replace('"', '\"') + '"'
    $quotedArguments = @(
        $uvicornArguments | ForEach-Object { '"' + ([string]$_).Replace('"', '\"') + '"' }
    )
    $nativeCommand = $quotedPython + " " + ($quotedArguments -join " ") + " 2>&1"

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $env:ComSpec
    $startInfo.Arguments = '/d /s /c "' + $nativeCommand + '"'
    $startInfo.WorkingDirectory = $projectRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true

    $serverProcess = New-Object System.Diagnostics.Process
    $serverProcess.StartInfo = $startInfo
    if (-not $serverProcess.Start()) {
        throw "Failed to start the LC AI Canvas server process."
    }
    [Environment]::SetEnvironmentVariable("LOG_TO_FILE", $previousLogToFile, "Process")

    $utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
    $logWriter = New-Object System.IO.StreamWriter($logPath, $true, $utf8WithoutBom)
    $logWriter.AutoFlush = $true
    while (-not $serverProcess.StandardOutput.EndOfStream) {
        $line = $serverProcess.StandardOutput.ReadLine()
        if ($null -ne $line) {
            Write-Host $line
            $logWriter.WriteLine($line)
        }
    }
    $serverProcess.WaitForExit()
    $serverExitCode = $serverProcess.ExitCode
}
finally {
    [Environment]::SetEnvironmentVariable("LOG_TO_FILE", $previousLogToFile, "Process")
    if ($null -ne $logWriter) {
        $logWriter.Dispose()
    }
    if ($null -ne $serverProcess) {
        Stop-LauncherProcessTree -RootProcessId $serverProcess.Id
        $serverProcess.Dispose()
    }
    if ($null -ne $launcherLock) {
        $launcherLock.Dispose()
    }
    Pop-Location
}

if ($serverExitCode -ne 0) {
    Write-Host "[ERROR] Uvicorn exited with code $serverExitCode. See $logPath" -ForegroundColor Red
    exit $serverExitCode
}
exit 0
