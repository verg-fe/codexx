$ErrorActionPreference='Stop'
$rt=$PSScriptRoot
$java=Join-Path $rt 'jdk\zulu25.36.205-ca-jdk25.0.4.1-win_x64\bin\java.exe'
$py=Join-Path $rt 'gateway-venv\Scripts\python.exe'
$jar=Join-Path $rt 'delamain.jar'
$gateway='G:\LocalCodex\tools\delamain\gateway\main.py'
foreach($port in @(8651,8650)){
 $ids=@(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue|Select-Object -ExpandProperty OwningProcess -Unique)
 foreach($id in $ids){
  $p=Get-CimInstance Win32_Process -Filter "ProcessId=$id"
  $managed=if($port -eq 8650){$p.ExecutablePath -ieq $java -and $p.CommandLine -like "*$jar*"}else{$p.ExecutablePath -ieq $py -and $p.CommandLine -like "*$gateway*"}
  if(!$managed){throw "Port $port belongs to an unrelated process; left untouched"}
  Stop-Process -Id $id
 }
}
[pscustomobject]@{status='stopped';ports=@(8651,8650)}