$ErrorActionPreference='Stop'
$rt=$PSScriptRoot
$repo='G:\LocalCodex\tools\delamain'
$s=Get-Content -Raw (Join-Path $rt 'secrets\delamain-auth.json')|ConvertFrom-Json
$java=Join-Path $rt 'jdk\zulu25.36.205-ca-jdk25.0.4.1-win_x64\bin\java.exe'
$jar=Join-Path $rt 'delamain.jar'
$py=Join-Path $rt 'gateway-venv\Scripts\python.exe'
$gateway=Join-Path $repo 'gateway\main.py'
$ver='20260724.4'
$apk=Join-Path $rt 'data\apks'
$out=Join-Path $rt 'data\output'
$idx=Join-Path $rt 'data\indices'
$logs=Join-Path $rt 'logs'
foreach($p in @($java,$jar,$py,$gateway)){if(!(Test-Path $p)){throw "Missing runtime file: $p"}}
New-Item -ItemType Directory -Force -Path $apk,$out,$idx,$logs|Out-Null
function Owner([int]$port){$ids=@(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue|Select-Object -ExpandProperty OwningProcess -Unique);if($ids.Count -gt 1){throw "Multiple owners on $port"};if(!$ids.Count){return $null};Get-CimInstance Win32_Process -Filter "ProcessId=$($ids[0])"}
function Healthy([string]$url){try{$h=Invoke-RestMethod -Uri $url -TimeoutSec 3;return ($h.status -in @('healthy','ok') -and $h.version -eq $ver)}catch{return $false}}
$o=Owner 8650
if($o){if($o.ExecutablePath -ine $java -or $o.CommandLine -notlike "*$jar*" -or !(Healthy 'http://127.0.0.1:8650/health')){throw '8650 is not the expected healthy Delamain backend; left untouched'}}else{
$env:DELAMAIN_AUTH_TOKEN=$s.backend_token;$env:DELAMAIN_WARMUP_ON_START='false';$env:JADX_FILE_ROOT=$apk
$jadx=Join-Path $rt 'lib\jadx-all-1.5.6.jar'
Start-Process -FilePath $java -ArgumentList @('-Xms512m','-Xmx4g','-XX:+UseSerialGC','-cp',($jar+';'+$jadx),'com.zin.delamain.Main','--bind','127.0.0.1','--port','8650','--output-dir',$out,'--index-dir',$idx,'--workers','2','--no-warmup-on-start') -WorkingDirectory $rt -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'backend.stdout.log') -RedirectStandardError (Join-Path $logs 'backend.stderr.log')|Out-Null
$ready=$false;for($i=0;$i -lt 60;$i++){if(Healthy 'http://127.0.0.1:8650/health'){$ready=$true;break};Start-Sleep 2};if(!$ready){throw 'Java backend did not become healthy; see G:\LocalCodex\tools\delamain-runtime\logs'}
}
$o=Owner 8651
if($o){if($o.ExecutablePath -ine $py -or $o.CommandLine -notlike "*$gateway*" -or !(Healthy 'http://127.0.0.1:8651/health')){throw '8651 is not the expected healthy Delamain gateway; left untouched'}}else{
$env:DELAMAIN_AUTH_TOKEN=$s.backend_token;$env:DELAMAIN_AUTH_TOKENS=$s.client_token;$env:JADX_FILE_ROOT=$apk;$env:PYTHONUNBUFFERED='1'
Start-Process -FilePath $py -ArgumentList @('-u',$gateway,'--host','127.0.0.1','--port','8651','--jadx','127.0.0.1:8650') -WorkingDirectory (Join-Path $repo 'gateway') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'gateway.stdout.log') -RedirectStandardError (Join-Path $logs 'gateway.stderr.log')|Out-Null
$ready=$false;for($i=0;$i -lt 60;$i++){if(Healthy 'http://127.0.0.1:8651/health'){$ready=$true;break};Start-Sleep 2};if(!$ready){throw 'MCP gateway did not become healthy; see G:\LocalCodex\tools\delamain-runtime\logs'}
}
[pscustomobject]@{status='healthy';version=$ver;endpoint='http://127.0.0.1:8651/mcp';apkRoot=$apk}