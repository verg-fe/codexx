$ErrorActionPreference='Stop'
$s=Get-Content -Raw (Join-Path $PSScriptRoot 'secrets\delamain-auth.json')|ConvertFrom-Json
if([string]::IsNullOrWhiteSpace($s.client_token)){throw 'Delamain client token is missing'}
[ordered]@{Authorization="Bearer $($s.client_token)"}|ConvertTo-Json -Compress