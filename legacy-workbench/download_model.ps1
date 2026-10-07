$ErrorActionPreference = 'Stop'
$taskRoot = 'D:\LocalCodex'
$taskModelRoot = 'G:\LocalCodex\models'
New-Item -ItemType Directory -Path "$taskRoot\runtime", $taskModelRoot, "$taskRoot\logs", "$taskRoot\cache" -Force | Out-Null
$taskZip = "$taskRoot\runtime\llama-b11327-vulkan.zip"
if (!(Test-Path -LiteralPath "$taskRoot\runtime\llama-server.exe")) {
    & curl.exe -L --fail --retry 8 --retry-all-errors -C - -o $taskZip 'https://github.com/ggml-org/llama.cpp/releases/download/b11327/llama-b11327-bin-win-vulkan-x64.zip'
    if ($LASTEXITCODE -ne 0) { throw 'Runtime download failed' }
    if ((Get-FileHash -LiteralPath $taskZip -Algorithm SHA256).Hash.ToLower() -ne '89d1308941d5a86182395a07f57286da3898a9530246e8f755c26ec71267d4a2') { throw 'Runtime checksum mismatch' }
    Expand-Archive -LiteralPath $taskZip -DestinationPath "$taskRoot\runtime" -Force
}
$taskModel = "$taskModelRoot\Jack-3.8-27B-V2-VL-16GB-VRAM.gguf"
if (!(Test-Path -LiteralPath $taskModel)) {
    & curl.exe -L --fail --retry 12 --retry-all-errors --speed-time 60 --speed-limit 1024 -C - -o "$taskModel.partial" 'https://huggingface.co/JackAgentLead/Jack-3.8-27B-V2-VL-16GB-VRAM/resolve/b5547a4b12824a1db2bf1af41504c3c7d600f8ac/Jack-3.8-27B-V2-VL-16GB-VRAM.gguf?download=true'
    if ($LASTEXITCODE -ne 0) { throw 'Model download failed; run again to resume' }
    if ((Get-FileHash -LiteralPath "$taskModel.partial" -Algorithm SHA256).Hash.ToLower() -ne 'c20dab06e201b2591318526031982152a79dcda2169c4d3bbb3826b1a5597e95') { throw 'Model checksum mismatch' }
    Move-Item -LiteralPath "$taskModel.partial" -Destination $taskModel
}
$taskVision = "$taskModelRoot\mmproj-Qwen3.8-27B-BF16.gguf"
if (!(Test-Path -LiteralPath $taskVision)) {
    & curl.exe -L --fail --retry 12 --retry-all-errors -C - -o "$taskVision.partial" 'https://huggingface.co/JackAgentLead/Jack-3.8-27B-V2-VL-16GB-VRAM/resolve/b5547a4b12824a1db2bf1af41504c3c7d600f8ac/mmproj-Qwen3.8-27B-BF16.gguf?download=true'
    if ($LASTEXITCODE -ne 0) { throw 'Vision download failed; run again to resume' }
    if ((Get-FileHash -LiteralPath "$taskVision.partial" -Algorithm SHA256).Hash.ToLower() -ne '13cb7bebccbd04afc8f4090cb949ecf8937cdf7377c5799b1a0c594e7c0d3e16') { throw 'Vision checksum mismatch' }
    Move-Item -LiteralPath "$taskVision.partial" -Destination $taskVision
}
'Downloaded and verified' | Set-Content -LiteralPath "$taskRoot\logs\download-complete.txt"
