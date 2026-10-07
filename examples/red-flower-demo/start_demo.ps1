# 一键启动：唤醒并前台启动演示App，然后启动单份持续 Frida 注入（停止请用 stop_demo.ps1）
$ErrorActionPreference = 'Stop'
$adb  = 'C:\Users\YOUR_USER\AppData\Local\VectorAndroidSdk\platform-tools\adb.exe'
$dev  = 'YOUR_ADB_SERIAL'
$py   = 'C:\Users\YOUR_USER\AppData\Local\Programs\Python\Python312\python.exe'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$flag = Join-Path $here 'demo_stop.flag'
$injectorPath = Join-Path $here 'inject_demo.py'
$existing = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'python.exe' -and $_.CommandLine -and $_.CommandLine.Contains($injectorPath)
}
if ($existing) { Write-Host 'Demo injector already running. Use stop_demo.ps1 to stop it.'; exit 0 }

if (Test-Path $flag) { Remove-Item $flag }
& $adb -s $dev shell 'su 0 input keyevent 224' | Out-Null
& $adb -s $dev shell 'am start -n com.redqueen.fridaflowerdemo/.MainActivity' | Out-Null
Write-Host 'Demo app launched; starting persistent injector (stoppable) ...'
& $py -u -X utf8 (Join-Path $here 'inject_demo.py') (Join-Path $here 'hook.js') '--stop-file' $flag
