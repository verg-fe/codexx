# 一键停止：通知运行中的持续注入恢复原监听器、卸载并退出（在注入器窗口可见 LISTENER_RESTORED / RESTORE_CONFIRMED / detached, bye）
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$flag = Join-Path $here 'demo_stop.flag'
New-Item -ItemType File -Force -Path $flag | Out-Null
Write-Host 'Stop requested: injector will restore original listener and detach within ~1-3 seconds.'
