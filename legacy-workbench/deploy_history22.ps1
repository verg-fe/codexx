$ErrorActionPreference = 'Stop'
$taskBase = (Resolve-Path -LiteralPath 'D:\LocalCodex').Path.TrimEnd('\')
$taskOldExe = 'D:\LocalCodex\app\MyCodex-history21\MyCodex.exe'
$taskStage = (Resolve-Path -LiteralPath 'D:\LocalCodex\staging\history-repair-22-ready\MyCodex').Path
$taskNew = [IO.Path]::GetFullPath('D:\LocalCodex\app\MyCodex-history22')
$taskShortcutName = ([char]0x6211).ToString() + ([char]0x7684).ToString() + 'Codex.cmd'
$taskShortcut = Join-Path 'C:\Users\18213\Desktop' $taskShortcutName
foreach ($taskTarget in @($taskStage,$taskNew)) {
    if (-not $taskTarget.StartsWith($taskBase + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected deployment target' }
}
function Assert-TaskIdle {
    $taskGuard = & 'C:\Python314\python.exe' -c 'import json,verify_kv20;print(json.dumps(verify_kv20.guard()))' | ConvertFrom-Json
    if (-not $taskGuard.safe) { throw ('Current answer preserved: ' + $taskGuard.reason) }
}
Assert-TaskIdle
$taskBackup = Join-Path $taskBase ('backups\before-history22-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $taskBackup | Out-Null
foreach ($taskFile in @('settings.json','conversations','instructions.md','model-catalog.json','codex-home\config.toml')) {
    Copy-Item -LiteralPath (Join-Path $taskBase $taskFile) -Destination $taskBackup -Recurse
}
Copy-Item -LiteralPath $taskShortcut -Destination $taskBackup
$taskProcesses = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $taskOldExe })
foreach ($taskProcess in ($taskProcesses | Where-Object { $_.CommandLine -notmatch '--gateway|--history-server' })) {
    $taskHandle = Get-Process -Id $taskProcess.ProcessId
    if (-not $taskHandle.CloseMainWindow()) { throw 'Desktop did not close normally.' }
    if (-not $taskHandle.WaitForExit(8000)) { throw 'Desktop is still busy; it was not forced to close.' }
}
Assert-TaskIdle
$taskChanged = $false
try {
    foreach ($taskProcess in ($taskProcesses | Where-Object { $_.CommandLine -match '--gateway' })) {
        $taskCurrent = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $taskProcess.ProcessId)
        if ($taskCurrent -and $taskCurrent.ExecutablePath -eq $taskOldExe) { Stop-Process -Id $taskProcess.ProcessId }
    }
    $taskChanged = $true
    if (Test-Path -LiteralPath $taskNew) {
        $taskExistingExe = Join-Path $taskNew 'MyCodex.exe'
        if (-not (Test-Path -LiteralPath $taskExistingExe) -or
            (Get-FileHash -LiteralPath $taskExistingExe).Hash -ne (Get-FileHash -LiteralPath (Join-Path $taskStage 'MyCodex.exe')).Hash) {
            throw 'Existing version directory does not match the verified release.'
        }
    } else {
        Copy-Item -LiteralPath $taskStage -Destination $taskNew -Recurse
    }
    $taskExe = Join-Path $taskNew 'MyCodex.exe'
    $taskPrepare = Start-Process -FilePath $taskExe -ArgumentList '--prepare-history-repair' -WindowStyle Hidden -Wait -PassThru
    if ($taskPrepare.ExitCode -ne 0) { throw 'Configuration preparation failed.' }
    Set-Content -LiteralPath $taskShortcut -Value @('@echo off','start "" "D:\LocalCodex\app\MyCodex-history22\MyCodex.exe"') -Encoding ascii
    $taskGateway = Start-Process -FilePath $taskExe -ArgumentList '--gateway' -WindowStyle Hidden -PassThru
    & 'C:\Python314\python.exe' (Join-Path $PSScriptRoot 'verify_gateway21_ready.py')
    if ($LASTEXITCODE -ne 0) { throw 'Updated gateway failed readiness check.' }
    @{installed=$true;executable=$taskExe;backup=$taskBackup;gateway_pid=$taskGateway.Id;
      adapter_version='2026-10-03-history-repair-22';work_context=76800;auto_compact=63488;
      unlimited_thinking=$true;time=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskBase 'deployment-history22.json') -Encoding utf8
    Write-Output 'History repair v22 installed; 75K working context and 62K compaction are prepared.'
} catch {
    if ($taskChanged) {
        if ($taskGateway) {
            $taskCurrent = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $taskGateway.Id)
            if ($taskCurrent -and $taskCurrent.ExecutablePath -eq (Join-Path $taskNew 'MyCodex.exe')) { Stop-Process -Id $taskGateway.Id }
        }
        foreach ($taskFile in @('settings.json','instructions.md','model-catalog.json')) {
            Copy-Item -LiteralPath (Join-Path $taskBackup $taskFile) -Destination (Join-Path $taskBase $taskFile)
        }
        Copy-Item -LiteralPath (Join-Path $taskBackup 'config.toml') -Destination (Join-Path $taskBase 'codex-home\config.toml')
        Copy-Item -LiteralPath (Join-Path $taskBackup $taskShortcutName) -Destination $taskShortcut
        Start-Process -FilePath $taskOldExe -ArgumentList '--gateway' -WindowStyle Hidden
        Start-Process -FilePath $taskOldExe
    }
    throw
}
