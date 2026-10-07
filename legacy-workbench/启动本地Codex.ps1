param([ValidateSet('jack-local', 'huihui-local')][string]$Profile = 'jack-local')
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath 'C:\Users\18213\Desktop\codexx'
try {
    & 'C:\Python314\python.exe' -c 'import core; core.prepare(); core.start_gateway()'
    if ($LASTEXITCODE -ne 0) { throw '本地模型启动失败，请查看 D:\LocalCodex\logs' }
    & 'D:\LocalCodex\engine\codex.exe' -p $Profile -C 'C:\Users\18213\Desktop\codexx'
} finally {
    Pop-Location
}
