$ErrorActionPreference = 'Stop'
$taskBase = (Resolve-Path -LiteralPath 'D:\LocalCodex').Path.TrimEnd('\')
$taskOldExe = 'D:\LocalCodex\app\MyCodex-hip18\MyCodex.exe'
$taskStage = (Resolve-Path -LiteralPath 'D:\LocalCodex\staging\history-workspace-19-ready\MyCodex').Path
$taskNew = [IO.Path]::GetFullPath('D:\LocalCodex\app\MyCodex-history19')
foreach ($taskTarget in @($taskStage,$taskNew)) {
    if (-not $taskTarget.StartsWith($taskBase + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected deployment target' }
}
if (Test-Path -LiteralPath $taskNew) { throw 'Version directory already exists.' }
$taskGuard = & 'C:\Python314\python.exe' (Join-Path $PSScriptRoot 'upgrade_guard.py') | ConvertFrom-Json
if (-not $taskGuard.safe) { throw ('Current task preserved: ' + $taskGuard.reason) }
Start-Sleep -Milliseconds 1500
$taskBackup = Join-Path $taskBase ('backups\before-history19-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $taskBackup | Out-Null
Copy-Item -LiteralPath (Join-Path $taskBase 'settings.json'),(Join-Path $taskBase 'conversations'),(Join-Path $taskBase 'instructions.md'),(Join-Path $taskBase 'model-catalog.json'),(Join-Path $taskBase 'codex-home\config.toml') -Destination $taskBackup -Recurse
Copy-Item -LiteralPath 'C:\Users\18213\Desktop\我的Codex.cmd' -Destination $taskBackup
$taskProcesses = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $taskOldExe })
foreach ($taskProcess in ($taskProcesses | Where-Object { $_.CommandLine -notmatch '--gateway' })) {
    $taskHandle = Get-Process -Id $taskProcess.ProcessId
    if (-not $taskHandle.CloseMainWindow()) { throw 'Desktop did not close normally.' }
    if (-not $taskHandle.WaitForExit(8000)) { throw 'Desktop is still busy; do not force it.' }
}
$taskGuard = & 'C:\Python314\python.exe' (Join-Path $PSScriptRoot 'upgrade_guard.py') | ConvertFrom-Json
if (-not $taskGuard.safe) { throw ('Installation stopped: ' + $taskGuard.reason) }
foreach ($taskProcess in ($taskProcesses | Where-Object { $_.CommandLine -match '--gateway' })) {
    $taskCurrent = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $taskProcess.ProcessId)
    if ($taskCurrent -and $taskCurrent.ExecutablePath -eq $taskOldExe) { Stop-Process -Id $taskProcess.ProcessId }
}
Copy-Item -LiteralPath $taskStage -Destination $taskNew -Recurse
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '历史与效能模式说明.md') -Destination $taskBase
$taskExe = Join-Path $taskNew 'MyCodex.exe'
$taskPrepare = Start-Process -FilePath $taskExe -ArgumentList '--prepare-history-performance' -WindowStyle Hidden -Wait -PassThru
if ($taskPrepare.ExitCode -ne 0) { throw 'New configuration preparation failed.' }
Set-Content -LiteralPath 'C:\Users\18213\Desktop\我的Codex.cmd' -Value @('@echo off','start "" "D:\LocalCodex\app\MyCodex-history19\MyCodex.exe"') -Encoding ascii
Start-Process -FilePath $taskExe -ArgumentList '--gateway' -WindowStyle Hidden
@{installed=$true;executable=$taskExe;backup=$taskBackup;settings='history memory 32K; max scheduling; unlimited thinking; no CPU weights';time=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskBase 'deployment-history19.json') -Encoding utf8
Write-Output ('history19 installed; gateway opened; backup: ' + $taskBackup)
