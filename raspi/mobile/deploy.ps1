param([string]$PiHost = 'pi@motorpi.local', [switch]$Install, [switch]$AccessPoint, [string]$ApkPath, [switch]$RotateAccessCode)
$ErrorActionPreference = 'Stop'
$source = $PSScriptRoot
& ssh -o BatchMode=yes $PiHost 'mkdir -p /home/pi/auto/mobile'
if ($LASTEXITCODE -ne 0) { throw 'SSH preparation failed' }
$files = @('control_core.py', 'bridge.py', 'ble_server.py', 'config.example.json', 'motorpi-mobile.service', 'motorpi-download.service', 'download.html', 'dbus-motorpi.conf', 'install.py')
$paths = $files | ForEach-Object { Join-Path $source $_ }
$paths += Join-Path $source 'access_code.py'
$paths += Join-Path $source 'commission.py'
$paths += Join-Path $source 'live_session.py'
& scp @paths "${PiHost}:/home/pi/auto/mobile/"
if ($LASTEXITCODE -ne 0) { throw 'Copy failed' }
if ($ApkPath) {
    if (-not (Test-Path -LiteralPath $ApkPath -PathType Leaf)) { throw 'APK not found' }
    & ssh -o BatchMode=yes $PiHost 'mkdir -p /home/pi/auto/mobile/download'
    if ($LASTEXITCODE -ne 0) { throw 'Download directory preparation failed' }
    & scp $ApkPath "${PiHost}:/home/pi/auto/mobile/download/motorpi.apk"
    if ($LASTEXITCODE -ne 0) { throw 'APK copy failed' }
}
if ($Install) {
    $command = 'sudo -n python3 /home/pi/auto/mobile/install.py'
    if ($AccessPoint) { $command += ' --access-point' }
    if ($RotateAccessCode) { $command += ' --rotate-access-code' }
    if ($ApkPath) { $command += ' --app-download' }
    & ssh -o BatchMode=yes $PiHost $command
    if ($LASTEXITCODE -ne 0) { throw 'Installation failed; inspect Pi output' }
}
