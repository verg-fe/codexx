$ErrorActionPreference = 'Stop'
$taskBase = (Resolve-Path -LiteralPath 'D:\LocalCodex').Path.TrimEnd('\')
$taskOldExe = 'D:\LocalCodex\app\MyCodex\MyCodex.exe'
$taskStage = (Resolve-Path -LiteralPath 'D:\LocalCodex\staging\live-thought-log-17-final\MyCodex').Path
$taskNew = [IO.Path]::GetFullPath('D:\LocalCodex\app\MyCodex-log17')
foreach ($taskTarget in @($taskStage,$taskNew)) {
    if (-not $taskTarget.StartsWith($taskBase + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected deployment target' }
}
if (Test-Path -LiteralPath $taskNew) { throw 'Version directory already exists.' }
$taskState = & 'C:\Python314\python.exe' -c "import core,json; print(json.dumps({'idle':not any(s.get('is_processing') for s in core.api('/slots')), 'pid':core.active_model().get('pid')}))"
$taskState = $taskState | ConvertFrom-Json
if (-not $taskState.idle) { throw 'Model task still running; leave it intact.' }
$taskBackup = Join-Path $taskBase ('backups\before-log17-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $taskBackup | Out-Null
Copy-Item -LiteralPath (Join-Path $taskBase 'settings.json'),(Join-Path $taskBase 'conversations') -Destination $taskBackup -Recurse
Copy-Item -LiteralPath 'C:\Users\18213\Desktop\我的Codex.cmd' -Destination $taskBackup

$taskProcesses = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $taskOldExe })
foreach ($taskProcess in ($taskProcesses | Where-Object { $_.CommandLine -notmatch '--gateway' })) {
    $taskHandle = Get-Process -Id $taskProcess.ProcessId
    if (-not $taskHandle.CloseMainWindow()) { throw 'Desktop did not close normally; no bundle replaced.' }
    if (-not $taskHandle.WaitForExit(8000)) { throw 'Desktop still busy; no bundle replaced.' }
}
foreach ($taskProcess in ($taskProcesses | Where-Object { $_.CommandLine -match '--gateway' })) {
    $taskCurrent = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $taskProcess.ProcessId)
    if ($taskCurrent -and $taskCurrent.ExecutablePath -eq $taskOldExe) { Stop-Process -Id $taskProcess.ProcessId }
}
# The live Vulkan model may use DLLs from the old application folder. Keep that
# folder intact and install the UI beside it, so there is no model restart.
Move-Item -LiteralPath $taskStage -Destination $taskNew
Copy-Item -LiteralPath '.\模型调研与使用说明.md' -Destination (Join-Path $taskBase '模型调研与使用说明.md')
Set-Content -LiteralPath 'C:\Users\18213\Desktop\我的Codex.cmd' -Value @('@echo off','start "" "D:\LocalCodex\app\MyCodex-log17\MyCodex.exe"') -Encoding ascii
Start-Process -FilePath (Join-Path $taskNew 'MyCodex.exe') -ArgumentList '--show-thought-log'
Write-Output ('log17 desktop opened; existing model PID retained: ' + $taskState.pid)
