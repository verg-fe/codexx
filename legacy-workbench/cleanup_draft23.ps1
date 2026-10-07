$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path -LiteralPath 'D:\LocalCodex').Path.TrimEnd('\')
$taskDeployment = Get-Content -LiteralPath (Join-Path $taskRoot 'deployment-draft23.json') -Raw | ConvertFrom-Json
if (-not $taskDeployment.installed) { throw 'Finish the verified desktop update before cleanup.' }
$taskAllowedParents = @(
    'C:\Users\18213\AppData\Local\pip',
    'C:\Users\18213\Desktop\codexx\build',
    'D:\LocalCodex\build',
    'D:\LocalCodex\staging',
    'D:\LocalCodex\downloads',
    'G:\LocalCodexV22\ssd_emergency'
)
$taskTargets = @('C:\Users\18213\AppData\Local\pip\Cache')
foreach ($taskName in @('history-repair-22','history-repair-21','MyCodex')) {
    $taskTargets += Join-Path 'C:\Users\18213\Desktop\codexx\build' $taskName
}
foreach ($taskName in @('history-workspace-19-ready','history-workspace-19-mtp','history-workspace-19-release','history-workspace-19-final','MyCodex')) {
    $taskTargets += Join-Path 'D:\LocalCodex\build' $taskName
}
foreach ($taskName in @('history-repair-22-ready','history-repair-21-ready','history-workspace-19-ready',
    'history-workspace-19-mtp','history-workspace-19-release','history-workspace-19-final','history-workspace-19',
    'live-thought-log-17','hip-backend-16-final','hip-backend-16')) {
    $taskTargets += Join-Path 'D:\LocalCodex\staging' $taskName
}
foreach ($taskName in @('llama-b11327-bin-win-rocm-10.0-x64.zip',
    'rocm_sdk_device_gfx1201-10.0.0-py3-none-win_amd64.whl','rocm_sdk_libraries-10.0.0-py3-none-win_amd64.whl')) {
    $taskTargets += Join-Path 'D:\LocalCodex\downloads' $taskName
}
$taskTargets += 'G:\LocalCodexV22\ssd_emergency\spill_ring.bin'
$taskBefore = @(Get-PSDrive C,D,G | Select-Object Name,Free)
$taskPlan = @()
$taskProcesses = @(Get-CimInstance Win32_Process)
foreach ($taskTarget in $taskTargets) {
    if (-not (Test-Path -LiteralPath $taskTarget)) { continue }
    $taskResolved = (Resolve-Path -LiteralPath $taskTarget).Path.TrimEnd('\')
    $taskMatches = @($taskAllowedParents | Where-Object {
        $taskResolved.StartsWith($_.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)
    })
    if ($taskMatches.Count -ne 1) { throw ('Unexpected cleanup target: '+$taskResolved) }
    $taskItem = Get-Item -LiteralPath $taskResolved -Force
    $taskChildren = if ($taskItem.PSIsContainer) { @(Get-ChildItem -LiteralPath $taskResolved -Recurse -Force) } else { @($taskItem) }
    if ($taskItem.Attributes -band [IO.FileAttributes]::ReparsePoint -or
        @($taskChildren | Where-Object {$_.Attributes -band [IO.FileAttributes]::ReparsePoint}).Count) {
        throw ('A cache contains a link; preserve it for review: '+$taskResolved)
    }
    if (@($taskProcesses | Where-Object {
        $_.ExecutablePath -and ($_.ExecutablePath.Equals($taskResolved,[StringComparison]::OrdinalIgnoreCase) -or
        $_.ExecutablePath.StartsWith($taskResolved+'\',[StringComparison]::OrdinalIgnoreCase))
    }).Count) { throw ('A cache is still in use: '+$taskResolved) }
    $taskBytes = ($taskChildren | Where-Object {-not $_.PSIsContainer} | Measure-Object -Property Length -Sum).Sum
    $taskPlan += @{path=$taskResolved;bytes=[long]$taskBytes;directory=[bool]$taskItem.PSIsContainer}
}
# The old G-drive reserve is a rebuildable spill file. Keep all ledgers/history
# alongside it, and refuse to remove the reserve if it is currently open.
$taskSpill = 'G:\LocalCodexV22\ssd_emergency\spill_ring.bin'
if (Test-Path -LiteralPath $taskSpill) {
    $taskReserveHandle = [IO.File]::Open($taskSpill,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::None)
    $taskReserveHandle.Dispose()
}
$taskReport = @{phase='planned';targets=$taskPlan;before=$taskBefore;
    preserved=@('model weights','all conversation history and logs','artworks','backups and installed old versions',
    'project source','old G-drive ledgers and memory','AMD drivers and shader caches');deleted=@();failed=@()}
$taskReportPath = Join-Path $taskRoot 'cleanup-draft23.json'
$taskReport | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $taskReportPath -Encoding utf8
foreach ($taskEntry in $taskPlan) {
    try {
        # Re-resolve the exact target immediately before native PowerShell deletion.
        $taskNow = (Resolve-Path -LiteralPath $taskEntry.path).Path.TrimEnd('\')
        if ($taskNow -ne $taskEntry.path) { throw 'Target changed since the cleanup plan.' }
        Remove-Item -LiteralPath $taskNow -Recurse -Force -ErrorAction Stop
        $taskReport.deleted += $taskEntry
    } catch {
        $taskReport.failed += @{path=$taskEntry.path;error=$_.Exception.Message}
    }
    $taskReport | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $taskReportPath -Encoding utf8
}
$taskReport.phase='complete'
$taskReport.after=@(Get-PSDrive C,D,G | Select-Object Name,Free)
$taskReport.logical_bytes_removed = [long](($taskReport.deleted | Measure-Object -Property bytes -Sum).Sum)
$taskReport.by_drive = @()
foreach ($taskDrive in @('C','D','G')) {
    $taskLogical = [long](($taskReport.deleted | Where-Object {$_.path.StartsWith($taskDrive+':\')} | Measure-Object -Property bytes -Sum).Sum)
    $taskActual = [long](@($taskReport.after | Where-Object {$_.Name -eq $taskDrive})[0].Free - @($taskReport.before | Where-Object {$_.Name -eq $taskDrive})[0].Free)
    $taskReport.by_drive += @{drive=$taskDrive;logical_bytes_removed=$taskLogical;free_space_increase=$taskActual}
}
$taskReport | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $taskReportPath -Encoding utf8
@{phase=$taskReport.phase;by_drive=$taskReport.by_drive;failures=$taskReport.failed.Count} | ConvertTo-Json -Depth 5
