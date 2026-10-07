$ErrorActionPreference = 'Stop'
$taskBase = (Resolve-Path -LiteralPath 'D:\LocalCodex').Path.TrimEnd('\')
$taskOldExe = 'D:\LocalCodex\app\MyCodex-steering24\MyCodex.exe'
$taskReportPath = Join-Path $taskBase 'deployment-native25.json'
if (Test-Path -LiteralPath $taskReportPath) {
    $taskPrior = Get-Content -LiteralPath $taskReportPath -Raw | ConvertFrom-Json
    if ($taskPrior.installed) { $taskOldExe = $taskPrior.executable }
}
$taskStage = (Resolve-Path -LiteralPath 'D:\LocalCodex\staging\native-thinking-25-ready\MyCodex').Path
$taskNew = [IO.Path]::GetFullPath('D:\LocalCodex\app\MyCodex-native25')
$taskVendor = [IO.Path]::GetFullPath('C:\Users\18213\Desktop\codex-jack-cli\vendor')
$taskCliStage = (Resolve-Path -LiteralPath 'D:\LocalCodex\staging\native-thinking-25-cli-ready').Path
$taskShortcutName = ([char]0x6211).ToString() + ([char]0x7684).ToString() + 'Codex.cmd'
$taskShortcut = Join-Path 'C:\Users\18213\Desktop' $taskShortcutName
foreach ($taskTarget in @($taskOldExe,$taskStage,$taskNew)) {
    if (-not $taskTarget.StartsWith($taskBase + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected deployment target' }
}
function Assert-TaskIdle {
    $taskGuard = & 'C:\Python314\python.exe' -c 'import json,native25_guard;print(json.dumps(native25_guard.guard()))' | ConvertFrom-Json
    if (-not $taskGuard.safe) { throw ('Current answer preserved: ' + $taskGuard.reason) }
}
Assert-TaskIdle
# A later model migration or explicit selection takes precedence over this Jack-only change.
& 'C:\Python314\python.exe' -c 'import core;from pathlib import Path;s=core.load_settings();a=core.active_model();p=core.api("/props");assert core.selected_model(s)==core.MODEL and a.get("model")==core.MODEL and Path(p.get("model_path","")).resolve()==core.model_file(core.MODEL).resolve(),"The active model selection changed; it was preserved."'
if ($LASTEXITCODE -ne 0) { throw 'The model selection changed; no update was applied.' }
foreach ($taskCheck in @('verification-build25.json','verification-native25-offline.json')) {
    $taskVerified = Get-Content -LiteralPath (Join-Path $taskBase $taskCheck) -Raw | ConvertFrom-Json
    if (-not $taskVerified.ok) { throw 'Release checks did not pass.' }
}
$taskSettingsObject = Get-Content -LiteralPath (Join-Path $taskBase 'settings.json') -Raw | ConvertFrom-Json
$taskSettingsObject | Add-Member -NotePropertyName jack_xml_enabled -NotePropertyValue $false -Force
$taskExpected = $taskSettingsObject | ConvertTo-Json -Depth 10 -Compress
$taskInstructionsBefore = (Get-FileHash -LiteralPath (Join-Path $taskBase 'instructions.md')).Hash
$taskBackup = Join-Path $taskBase ('backups\before-native25-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $taskBackup | Out-Null
foreach ($taskFile in @('settings.json','conversations','instructions.md','model-catalog.json','codex-home\config.toml')) {
    Copy-Item -LiteralPath (Join-Path $taskBase $taskFile) -Destination $taskBackup -Recurse
}
Copy-Item -LiteralPath $taskShortcut -Destination $taskBackup
New-Item -ItemType Directory -Path (Join-Path $taskBackup 'cli-vendor') | Out-Null
foreach ($taskName in @('core.py','model_templates.py','gguf_info.py')) {
    $taskFile = Join-Path $taskVendor $taskName
    if (Test-Path -LiteralPath $taskFile) { Copy-Item -LiteralPath $taskFile -Destination (Join-Path $taskBackup 'cli-vendor') }
}
foreach ($taskProfile in @('jack-local.config.toml','huihui-local.config.toml')) {
    $taskFile = Join-Path 'C:\Users\18213\.codex' $taskProfile
    if (Test-Path -LiteralPath $taskFile) { Copy-Item -LiteralPath $taskFile -Destination $taskBackup }
}
$taskProcesses = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $taskOldExe })
foreach ($taskProcess in ($taskProcesses | Where-Object { $_.CommandLine -notmatch '--gateway|--history-server' })) {
    $taskHandle = Get-Process -Id $taskProcess.ProcessId
    if (-not $taskHandle.CloseMainWindow()) { throw 'Desktop did not close normally.' }
    if (-not $taskHandle.WaitForExit(8000)) { throw 'Desktop remains busy; it was preserved.' }
}
Assert-TaskIdle
$taskChanged = $false
$taskGateway = $null
try {
    foreach ($taskProcess in ($taskProcesses | Where-Object { $_.CommandLine -match '--gateway' })) {
        $taskCurrent = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $taskProcess.ProcessId)
        if ($taskCurrent -and $taskCurrent.ExecutablePath -eq $taskOldExe) { Stop-Process -Id $taskProcess.ProcessId }
    }
    $taskChanged = $true
    if (Test-Path -LiteralPath $taskNew) {
        if ((Get-FileHash -LiteralPath (Join-Path $taskNew 'MyCodex.exe')).Hash -ne (Get-FileHash -LiteralPath (Join-Path $taskStage 'MyCodex.exe')).Hash) {
            throw 'Existing version does not match the verified release.'
        }
    } else { Copy-Item -LiteralPath $taskStage -Destination $taskNew -Recurse }
    $taskExe = Join-Path $taskNew 'MyCodex.exe'
    $taskPrepare = Start-Process -FilePath $taskExe -ArgumentList '--prepare-native-thinking' -WindowStyle Hidden -Wait -PassThru
    if ($taskPrepare.ExitCode -ne 0) { throw 'Configuration preparation failed.' }
    $taskActual = Get-Content -LiteralPath (Join-Path $taskBase 'settings.json') -Raw | ConvertFrom-Json | ConvertTo-Json -Depth 10 -Compress
    if ($taskExpected -ne $taskActual) { throw 'Settings changed beyond the authorized XML toggle.' }
    if ($taskInstructionsBefore -ne (Get-FileHash -LiteralPath (Join-Path $taskBase 'instructions.md')).Hash) { throw 'Base instructions changed unexpectedly.' }
    $taskGateway = Start-Process -FilePath $taskExe -ArgumentList '--gateway' -WindowStyle Hidden -PassThru
    & 'C:\Python314\python.exe' (Join-Path $PSScriptRoot 'verify_gateway21_ready.py')
    if ($LASTEXITCODE -ne 0) { throw 'Updated gateway failed readiness check.' }
    & 'C:\Python314\python.exe' (Join-Path $PSScriptRoot 'activate_native25.py')
    if ($LASTEXITCODE -ne 0) { throw 'Model template reload failed.' }
    & 'C:\Python314\python.exe' (Join-Path $PSScriptRoot 'verify_native25_runtime.py')
    if ($LASTEXITCODE -ne 0) { throw 'Real model verification failed; original mode will be restored.' }
    foreach ($taskName in @('core.py','model_templates.py','gguf_info.py')) {
        Copy-Item -LiteralPath (Join-Path $taskCliStage $taskName) -Destination (Join-Path $taskVendor $taskName)
    }
    Set-Content -LiteralPath $taskShortcut -Value @('@echo off','start "" "D:\LocalCodex\app\MyCodex-native25\MyCodex.exe"') -Encoding ascii
    @{installed=$true;executable=$taskExe;backup=$taskBackup;gateway_pid=$taskGateway.Id;
      adapter_version='2026-10-03-native-thinking-25';work_context=76800;auto_compact=63488;
      unlimited_thinking=$true;jack_xml_enabled=$false;weights_modified=$false;native_turn_steer=$true;
      base_instructions_unchanged=$true;real_model_verified=$true;
      time=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $taskReportPath -Encoding utf8
    Start-Process -FilePath $taskExe -ArgumentList '--show-model-options' -WindowStyle Normal
    Write-Output 'Native thinking v25 installed and verified. XML directive removed; thinking remains unlimited.'
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
        foreach ($taskName in @('core.py','model_templates.py','gguf_info.py')) {
            $taskOriginal = Join-Path $taskBackup ('cli-vendor\'+$taskName)
            if (Test-Path -LiteralPath $taskOriginal) { Copy-Item -LiteralPath $taskOriginal -Destination (Join-Path $taskVendor $taskName) }
        }
        foreach ($taskProfile in @('jack-local.config.toml','huihui-local.config.toml')) {
            if (Test-Path -LiteralPath (Join-Path $taskBackup $taskProfile)) {
                Copy-Item -LiteralPath (Join-Path $taskBackup $taskProfile) -Destination (Join-Path 'C:\Users\18213\.codex' $taskProfile)
            }
        }
        & 'C:\Python314\python.exe' -c 'import core;s=core.load_settings();a=core.active_model();core._start_model(core.selected_model(s),a.get("context",core.GPU_CONTEXT_LIMIT),True,core.context_for(s,core.selected_model(s)))'
        Start-Process -FilePath $taskOldExe -ArgumentList '--gateway' -WindowStyle Hidden
        Start-Process -FilePath $taskOldExe -WindowStyle Normal
    }
    throw
}
