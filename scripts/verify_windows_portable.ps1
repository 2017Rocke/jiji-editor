# Run only on the disposable Windows CI runner: temporary firewall rules isolate
# the packaged application while leaving GitHub/Python test orchestration online.
param([Parameter(Mandatory = $true)][string]$Executable)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Resolve-Path -LiteralPath $Executable).Path
foreach ($relative in @('coreclr.dll', 'hostfxr.dll', 'System.Windows.Forms.dll', 'webview2/msedgewebview2.exe')) {
    if (-not (Test-Path -LiteralPath (Join-Path $root $relative))) { throw "Missing bundled runtime: $relative" }
}
if (Test-Path -LiteralPath (Join-Path $root 'WebView2Setup.exe')) { throw 'The portable package must not contain a runtime installer' }
& python scripts/verify_windows_dependencies.py $root
if ($LASTEXITCODE -ne 0) { throw 'Portable native dependency verification failed' }

foreach ($service in @('MpsSvc', 'BFE')) {
    if ((Get-Service -Name $service).Status -ne 'Running') { throw "Firewall service is not running: $service" }
}
# Establish that the probe destination is reachable from this runner first.
# The packaged host must then fail the same TCP connection under its rule.
$probeAddress = $null
foreach ($address in [System.Net.Dns]::GetHostAddresses('api.github.com')) {
    if ($address.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) { continue }
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        if ($client.ConnectAsync($address, 443).Wait(5000) -and $client.Connected) {
            $probeAddress = $address.ToString()
            break
        }
    } catch { } finally { $client.Dispose() }
}
if (-not $probeAddress) { throw 'Cannot establish the external network probe baseline' }

$prefix = 'JijiPortableVerification-' + [guid]::NewGuid().ToString('N')
$profiles = @(Get-NetFirewallProfile | Select-Object Name, Enabled)
$rules = @()
$environmentNames = @('DOTNET_ROOT', 'DOTNET_ROOT_X64', 'DOTNET_MULTILEVEL_LOOKUP', 'DOTNET_ROLL_FORWARD', 'WEBVIEW2_BROWSER_EXECUTABLE_FOLDER', 'JIJI_OFFLINE_PROBE_ADDRESS')
$previousEnvironment = @{}
foreach ($name in $environmentNames) { $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
try {
    Set-NetFirewallProfile -Profile Domain, Private, Public -Enabled True
    if (@(Get-NetFirewallProfile | Where-Object { -not $_.Enabled }).Count -ne 0) { throw 'Firewall isolation could not be enabled' }
    # All external IPv4/IPv6 addresses; the document engine uses IPv4 loopback.
    $external = @('0.0.0.0-126.255.255.255', '128.0.0.0-255.255.255.255', '::2-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff')
    $executables = @(Get-ChildItem -LiteralPath $root -Filter '*.exe' -Recurse -File)
    foreach ($file in $executables) {
        $name = "$prefix-$($rules.Count)"
        New-NetFirewallRule -Name $name -DisplayName $name -Direction Outbound -Action Block -Enabled True -Profile Any -Program $file.FullName -RemoteAddress $external | Out-Null
        $rules += $name
    }
    foreach ($name in $rules) {
        $active = Get-NetFirewallRule -PolicyStore ActiveStore -Name $name
        if ($active.Enabled -ne 'True' -or $active.Action -ne 'Block' -or $active.Direction -ne 'Outbound') {
            throw 'The external network isolation rule is not active'
        }
    }
    # Invalid machine-runtime paths expose accidental use of global .NET or
    # WebView2. The host explicitly chooses and verifies its packaged WebView2.
    $missing = Join-Path $env:RUNNER_TEMP "$prefix-no-system-runtime"
    $env:DOTNET_ROOT = $missing
    $env:DOTNET_ROOT_X64 = $missing
    $env:DOTNET_MULTILEVEL_LOOKUP = '0'
    $env:DOTNET_ROLL_FORWARD = 'Disable'
    $env:WEBVIEW2_BROWSER_EXECUTABLE_FOLDER = $missing
    $env:JIJI_OFFLINE_PROBE_ADDRESS = $probeAddress
    & python scripts/verify_windows_native.py $Executable
    if ($LASTEXITCODE -ne 0) { throw 'Portable Windows native verification failed' }
    $nativeReport = Get-Content -Raw -LiteralPath 'output/native-windows/native-verification.json' | ConvertFrom-Json
    if ($nativeReport.outboundProbeBlocked -ne $true) { throw 'The packaged host did not verify its external connection was blocked' }
    @{
        passed = $true
        externalNetworkBlocked = $true
        blockedExecutables = $executables.Count
        systemRuntimePathsUnavailable = $true
    } | ConvertTo-Json | Set-Content -LiteralPath 'output/native-portable-verification.json' -Encoding utf8
} finally {
    foreach ($name in $rules) { Remove-NetFirewallRule -Name $name -ErrorAction SilentlyContinue }
    foreach ($profile in $profiles) { Set-NetFirewallProfile -Profile $profile.Name -Enabled $profile.Enabled }
    foreach ($name in $environmentNames) { [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process') }
}
