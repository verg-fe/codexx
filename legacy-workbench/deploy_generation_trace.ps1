$ErrorActionPreference = 'Stop'
$taskBase = (Resolve-Path -LiteralPath 'D:\LocalCodex').Path.TrimEnd('\')
$taskInstalled = (Resolve-Path -LiteralPath 'D:\LocalCodex\app\MyCodex').Path
$taskStage = (Resolve-Path -LiteralPath 'D:\LocalCodex\staging\generation-trace-15\MyCodex').Path
$taskBackup = [IO.Path]::GetFullPath('D:\LocalCodex\backups\app-before-generation-trace-15')
foreach ($taskTarget in @($taskInstalled, $taskStage, $taskBackup)) {
    if (-not $taskTarget.StartsWith($taskBase + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Unexpected deployment target outside D:\LocalCodex'
    }
}
if (Test-Path -LiteralPath $taskBackup) { throw 'Backup already exists; deployment has not started.' }
if (-not (Test-Path -LiteralPath (Join-Path $taskStage 'MyCodex.exe'))) { throw 'Missing staged executable.' }

# Check just the owned local engine. Never stop the separate cloud Codex app.
$taskIdle = & 'C:\Python314\python.exe' -c "import core; print('idle' if not any(s.get('is_processing') for s in core.api('/slots')) else 'busy')"
if ($taskIdle -ne 'idle') { throw 'A model request is running; leave it intact.' }
$taskDataBackup = Join-Path $taskBase ('backups\before-generation-trace-15-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $taskDataBackup | Out-Null
foreach ($taskName in @('settings.json', 'conversations')) {
    Copy-Item -LiteralPath (Join-Path $taskBase $taskName) -Destination $taskDataBackup -Recurse
}

$taskExe = Join-Path $taskInstalled 'MyCodex.exe'
$taskProcesses = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $taskExe })
$taskDesktop = @($taskProcesses | Where-Object { $_.CommandLine -notmatch '--gateway' })
foreach ($taskProcess in $taskDesktop) {
    $taskHandle = Get-Process -Id $taskProcess.ProcessId
    if (-not $taskHandle.CloseMainWindow()) { throw 'Could not close local desktop normally; no files moved.' }
    if (-not $taskHandle.WaitForExit(8000)) { throw 'Local desktop is still busy; no files moved.' }
}
# The frozen gateway/model may hold the installed runtime DLLs until exited.
& 'C:\Python314\python.exe' -c "import core; core.stop_model(); print('owned model stopped')"
if ($LASTEXITCODE -ne 0) { throw 'Could not stop owned model.' }
foreach ($taskProcess in ($taskProcesses | Where-Object { $_.CommandLine -match '--gateway' })) {
    $taskCurrent = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $taskProcess.ProcessId)
    if ($taskCurrent -and $taskCurrent.ExecutablePath -eq $taskExe) {
        Stop-Process -Id $taskProcess.ProcessId
        (Get-Process -Id $taskProcess.ProcessId -ErrorAction SilentlyContinue) | Wait-Process -Timeout 8
    }
}
Move-Item -LiteralPath $taskInstalled -Destination $taskBackup
try {
    Move-Item -LiteralPath $taskStage -Destination $taskInstalled
} catch {
    Move-Item -LiteralPath $taskBackup -Destination $taskInstalled
    throw
}
Copy-Item -LiteralPath '.\模型调研与使用说明.md' -Destination (Join-Path $taskBase '模型调研与使用说明.md')
Start-Process -FilePath (Join-Path $taskInstalled 'MyCodex.exe')
Write-Output 'generation-trace-15 installed; conversations and settings backed up; desktop reopened'
