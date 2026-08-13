[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet("Install", "Show", "Remove")]
    [string]$Action = "Show",
    [string]$DestinationRoot = "",
    [string]$TaskName = "LC AI Canvas Complete Backup",
    [datetime]$DailyAt = ([datetime]::Today.AddHours(3)),
    [ValidateRange(1, 3650)]
    [int]$RetentionDays = 30,
    [ValidateRange(1, 1000)]
    [int]$MinimumBundles = 7
)

$ErrorActionPreference = "Stop"
$projectRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$backupScript = Join-Path $PSScriptRoot "backup_app_data.ps1"

if ($Action -eq "Show") {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        Write-Output "Scheduled task is not installed: $TaskName"
    }
    else {
        $task | Select-Object TaskName, State, Description | Format-List | Out-String | Write-Output
        Get-ScheduledTaskInfo -TaskName $TaskName |
            Select-Object LastRunTime, LastTaskResult, NextRunTime |
            Format-List | Out-String | Write-Output
    }
    exit 0
}

if ($Action -eq "Remove") {
    if ($PSCmdlet.ShouldProcess($TaskName, "Remove scheduled backup task")) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
    }
    exit 0
}

if ([string]::IsNullOrWhiteSpace($DestinationRoot)) {
    throw "DestinationRoot is required when Action=Install. Use an external or separately protected location."
}
$destination = [System.IO.Path]::GetFullPath($DestinationRoot)
$projectPrefix = $projectRoot.TrimEnd('\') + '\'
if ($destination.Equals($projectRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
    $destination.StartsWith($projectPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Scheduled backups must be outside the project directory: $destination"
}

$arguments = @(
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy", "Bypass",
    "-File", ('"' + $backupScript + '"'),
    "-DestinationRoot", ('"' + $destination + '"'),
    "-RetentionDays", [string]$RetentionDays,
    "-MinimumBundles", [string]$MinimumBundles
) -join " "

if ($PSCmdlet.ShouldProcess($TaskName, "Install daily verified complete backup task")) {
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    $taskAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $projectRoot
    $trigger = New-ScheduledTaskTrigger -Daily -At $DailyAt
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Hours 12)
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $taskAction `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Verified LC AI Canvas DB, outputs, and principal-secret backup" `
        -Force | Out-Null
    Write-Output "Installed scheduled task: $TaskName"
    Write-Output "Destination: $destination"
    Write-Output "Next run: $((Get-ScheduledTaskInfo -TaskName $TaskName).NextRunTime)"
}
