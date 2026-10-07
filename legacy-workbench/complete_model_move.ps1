$ErrorActionPreference = 'Stop'
$migrationPath = 'D:\LocalCodex\model-migration.json'
$migration = Get-Content -LiteralPath $migrationPath -Raw | ConvertFrom-Json
if (-not $migration.ok -or -not $migration.configuration_applied -or $migration.phase -ne 'files_verified') {
    throw 'Model destinations have not been verified and activated'
}
$sourceRoot = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath 'D:\LocalCodex\models').Path)
$destinationRoot = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath 'G:\LocalCodex\models').Path)
if ($sourceRoot -ne 'D:\LocalCodex\models' -or $destinationRoot -ne 'G:\LocalCodex\models') {
    throw 'Unexpected resolved model directories'
}
$allowedFiles = @(
    @{ Name='Jack-3.8-27B-V2-VL-16GB-VRAM.gguf'; Size=12120033600; Hash='c20dab06e201b2591318526031982152a79dcda2169c4d3bbb3826b1a5597e95' },
    @{ Name='Huihui-Qwen3.8-27B-abliterated-Q4_K.gguf'; Size=16810714400; Hash='6c2c13cef89238c3604d756b07b3ef5fafebbd61095feb8553ff449c95e4c1c6' },
    @{ Name='mmproj-Qwen3.8-27B-BF16.gguf'; Size=931146528; Hash='13cb7bebccbd04afc8f4090cb949ecf8937cdf7377c5799b1a0c594e7c0d3e16' }
)
$removeTargets = @()
foreach ($expectedFile in $allowedFiles) {
    $record = @($migration.files | Where-Object { $_.name -eq $expectedFile.Name })
    if ($record.Count -ne 1 -or -not $record[0].verified -or $record[0].size -ne $expectedFile.Size -or $record[0].sha256 -ne $expectedFile.Hash) {
        throw 'Verification record is missing or mismatched'
    }
    $sourcePath = [IO.Path]::GetFullPath((Join-Path $sourceRoot $expectedFile.Name))
    $destinationPath = [IO.Path]::GetFullPath((Join-Path $destinationRoot $expectedFile.Name))
    if ([IO.Path]::GetDirectoryName($sourcePath) -ne $sourceRoot -or [IO.Path]::GetDirectoryName($destinationPath) -ne $destinationRoot) {
        throw 'File paths are outside the specified model directories'
    }
    $destinationFile = Get-Item -LiteralPath $destinationPath
    if ($destinationFile.Length -ne $expectedFile.Size -or ($destinationFile.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Verified destination has changed'
    }
    if (Test-Path -LiteralPath $sourcePath) {
        $sourceFile = Get-Item -LiteralPath $sourcePath
        if ($sourceFile.Length -ne $expectedFile.Size -or ($sourceFile.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Source has changed; left intact'
        }
        $removeTargets += $sourcePath
    }
}
foreach ($sourcePath in $removeTargets) {
    Remove-Item -LiteralPath $sourcePath -Force
}
$migration.sources_removed = $true
$migration.phase = 'complete'
$encoded = $migration | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText($migrationPath, $encoded, [Text.UTF8Encoding]::new($false))
'Verified models moved to G; original D files removed'
