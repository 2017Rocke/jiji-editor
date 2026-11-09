# Validate the same published update ZIP on every supported, unmodified base.
param([Parameter(Mandatory = $true)][string]$NewExecutable)
$ErrorActionPreference = 'Stop'
$version = (Get-Content VERSION -Raw).Trim()
if ($version -ne '0.3.3') { throw 'This compatibility matrix targets v0.3.3 only' }
$newPackage = Split-Path -Parent $NewExecutable
$update = "output/JijiEditor-$version-Windows-startup-update.zip"
$testRoot = Join-Path $env:RUNNER_TEMP '吉吉 启动更新验证'
New-Item -ItemType Directory -Path $testRoot -Force | Out-Null

function Get-VerifiedReleaseFile([string]$Tag, [string]$Name, [string]$Hash) {
    $destination = Join-Path $testRoot $Name
    Invoke-WebRequest -Uri "https://github.com/2017Rocke/jiji-editor/releases/download/$Tag/$Name" -OutFile $destination
    if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $Hash) {
        throw "Published file does not match its pinned SHA-256: $Name"
    }
    return $destination
}

$old31 = Get-VerifiedReleaseFile 'v0.3.1' 'JijiEditor-0.3.1-Windows-x64.zip' '940f3da83dc8bc45691d579138151c68fedaa825a3a9e50cfd8066e571d4749e'
$old32 = Get-VerifiedReleaseFile 'v0.3.2' 'JijiEditor-0.3.2-Windows-x64.zip' 'f3632311304b971addeeb247c9d25a282b6735449ee0c133dba2baab5a6f60f6'
$patch32 = Get-VerifiedReleaseFile 'v0.3.2' 'JijiEditor-0.3.2-Windows-startup-update.zip' '239de87e1cb3be999ef31d42d55bfd49d51bff7a648d339149aa603b44f184df'
$cases = @(
    @{ Name = 'v031'; Archive = $old31; Patch = $null },
    @{ Name = 'v031-updated-to-v032'; Archive = $old31; Patch = $patch32 },
    @{ Name = 'v032'; Archive = $old32; Patch = $null }
)
$first = $true
foreach ($case in $cases) {
    $destination = Join-Path $testRoot $case.Name
    if (Test-Path -LiteralPath $destination) { Remove-Item -LiteralPath $destination -Recurse -Force }
    Expand-Archive -LiteralPath $case.Archive -DestinationPath $destination -Force
    $package = Join-Path $destination 'JijiEditor-Windows-x64'
    if ($case.Patch) { Expand-Archive -LiteralPath $case.Patch -DestinationPath $package -Force }
    $checkZip = if ($first) { $update } else { Join-Path $testRoot ($case.Name + '-dependency-check.zip') }
    $checkReport = "output/startup-update-$($case.Name)-verification.json"
    python scripts/build_windows_startup_update.py $package $newPackage --output $checkZip --report $checkReport
    if ($LASTEXITCODE -ne 0) { throw "Startup update dependencies differ from $($case.Name)" }
    if ($first) {
        Copy-Item -LiteralPath $checkReport -Destination 'output/startup-update-verification.json'
        $first = $false
    }
    # Apply the one public ZIP, including when the base has a different VERSION.
    Expand-Archive -LiteralPath $update -DestinationPath $package -Force
    $evidence = "output/native-startup-update-$($case.Name)"
    $summary = "$evidence-verification.json"
    if (Test-Path -LiteralPath $evidence) { Remove-Item -LiteralPath $evidence -Recurse -Force }
    foreach ($stale in @($summary, 'output/native-windows-verification.json')) {
        if (Test-Path -LiteralPath $stale) { Remove-Item -LiteralPath $stale -Force }
    }
    try {
        python scripts/verify_windows_native.py (Join-Path $package 'JijiEditor.exe')
        if ($LASTEXITCODE -ne 0) { throw "Patched $($case.Name) did not pass native/permission verification" }
    } finally {
        if (Test-Path -LiteralPath 'output/native-windows') {
            Copy-Item -LiteralPath 'output/native-windows' -Destination $evidence -Recurse
        }
        if (Test-Path -LiteralPath 'output/native-windows-verification.json') {
            Copy-Item -LiteralPath 'output/native-windows-verification.json' -Destination $summary
        }
    }
}
