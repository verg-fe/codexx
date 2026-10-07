$ErrorActionPreference = 'Stop'
$taskBase = (Resolve-Path -LiteralPath 'D:\LocalCodex').Path.TrimEnd('\')
$taskOldExe = 'D:\LocalCodex\app\MyCodex-log17\MyCodex.exe'
$taskStage = (Resolve-Path -LiteralPath 'D:\LocalCodex\staging\hip-and-thought-log-18\MyCodex').Path
$taskNew = [IO.Path]::GetFullPath('D:\LocalCodex\app\MyCodex-hip18')
foreach ($taskTarget in @($taskStage,$taskNew)) {
    if (-not $taskTarget.StartsWith($taskBase + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected deployment target' }
}
if (Test-Path -LiteralPath $taskNew) { throw 'Version directory already exists.' }
$taskIdle = & 'C:\Python314\python.exe' -c "import core; print(not any(s.get('is_processing') for s in core.api('/slots')))"
if ($taskIdle.Trim() -ne 'True') { throw 'A model task is running; leave it intact.' }
$taskBackup = Join-Path $taskBase ('backups\before-hip18-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $taskBackup | Out-Null
Copy-Item -LiteralPath (Join-Path $taskBase 'settings.json'),(Join-Path $taskBase 'conversations'),(Join-Path $taskBase 'instructions.md') -Destination $taskBackup -Recurse
Copy-Item -LiteralPath 'C:\Users\18213\Desktop\我的Codex.cmd' -Destination $taskBackup
$taskProcesses = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $taskOldExe })
foreach ($taskProcess in ($taskProcesses | Where-Object { $_.CommandLine -notmatch '--gateway' })) {
    $taskHandle = Get-Process -Id $taskProcess.ProcessId
    if (-not $taskHandle.CloseMainWindow()) { throw 'Desktop did not close normally.' }
    if (-not $taskHandle.WaitForExit(8000)) { throw 'Desktop is still busy.' }
}
foreach ($taskProcess in ($taskProcesses | Where-Object { $_.CommandLine -match '--gateway' })) {
    $taskCurrent = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $taskProcess.ProcessId)
    if ($taskCurrent -and $taskCurrent.ExecutablePath -eq $taskOldExe) { Stop-Process -Id $taskProcess.ProcessId }
}
Move-Item -LiteralPath $taskStage -Destination $taskNew
Set-Content -LiteralPath 'C:\Users\18213\Desktop\我的Codex.cmd' -Value @('@echo off','start "" "D:\LocalCodex\app\MyCodex-hip18\MyCodex.exe"') -Encoding ascii
Start-Process -FilePath (Join-Path $taskNew 'MyCodex.exe') -ArgumentList '--gateway' -WindowStyle Hidden
Write-Output ('hip18 installed; gateway opened; backup: ' + $taskBackup)
