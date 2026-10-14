param([string]$PiHost = 'pi@motorpi.local', [switch]$Install, [switch]$AccessPoint, [string]$ApkPath, [switch]$BuildApk, [switch]$RotateAccessCode)
$ErrorActionPreference = 'Stop'
$source = $PSScriptRoot
$repo = Split-Path (Split-Path $source)
$app = Join-Path $repo 'mobile_app'
$version = ((Get-Content (Join-Path $app 'pubspec.yaml')) -match '^version:' | Select-Object -First 1) -replace '^version:\s*', ''
if ($BuildApk) {
    # Flutter lives ignored in .tools/; build so the download page always serves the current app.
    $flutter = Join-Path $repo '.tools\flutter\bin\flutter.bat'
    if (-not (Test-Path -LiteralPath $flutter)) { throw "Flutter not found at $flutter" }
    # The JDK's Unix-socket selector pipe fails under an 8.3 short TEMP path ("Unable to
    # establish loopback connection" in the Gradle daemon); give it a plain directory.
    if (-not $env:JAVA_TOOL_OPTIONS) {
        New-Item -ItemType Directory -Force 'C:\Temp' | Out-Null
        $env:JAVA_TOOL_OPTIONS = '-Djdk.net.unixdomain.tmpdir=C:\Temp'
    }
    Push-Location $app
    try {
        & $flutter pub get
        if ($LASTEXITCODE -ne 0) { throw 'flutter pub get failed' }
        & $flutter test
        if ($LASTEXITCODE -ne 0) { throw 'Flutter tests failed; not deploying' }
        & $flutter build apk --release
        if ($LASTEXITCODE -ne 0) { throw 'APK build failed' }
    } finally { Pop-Location }
    $ApkPath = Join-Path $app 'build\app\outputs\flutter-apk\app-release.apk'
}
& ssh -o BatchMode=yes $PiHost 'mkdir -p /home/pi/auto/mobile'
if ($LASTEXITCODE -ne 0) { throw 'SSH preparation failed' }
$files = @('control_core.py', 'bridge.py', 'wifi_server.py', 'config.example.json', 'motorpi-mobile.service', 'motorpi-download.service', 'download.html', 'install.py', 'access_code.py', 'commission.py', 'live_session.py')
$paths = $files | ForEach-Object { Join-Path $source $_ }
& scp @paths "${PiHost}:/home/pi/auto/mobile/"
if ($LASTEXITCODE -ne 0) { throw 'Copy failed' }
if ($ApkPath) {
    if (-not (Test-Path -LiteralPath $ApkPath -PathType Leaf)) { throw 'APK not found' }
    & ssh -o BatchMode=yes $PiHost 'mkdir -p /home/pi/auto/mobile/download && rm -f /home/pi/auto/mobile/ble_server.py /home/pi/auto/mobile/dbus-motorpi.conf'
    if ($LASTEXITCODE -ne 0) { throw 'Download directory preparation failed' }
    & scp $ApkPath "${PiHost}:/home/pi/auto/mobile/download/motorpi.apk"
    if ($LASTEXITCODE -ne 0) { throw 'APK copy failed' }
    $versionFile = Join-Path ([IO.Path]::GetTempPath()) 'motorpi-version.txt'
    [IO.File]::WriteAllText($versionFile, $version + "`n")
    & scp $versionFile "${PiHost}:/home/pi/auto/mobile/download/version.txt"
    if ($LASTEXITCODE -ne 0) { throw 'Version copy failed' }
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ApkPath).Hash.ToLower()
    Write-Host "APK $version, SHA-256 $hash"
}
if ($Install) {
    $command = 'sudo -n python3 /home/pi/auto/mobile/install.py'
    if ($AccessPoint) { $command += ' --access-point' }
    if ($RotateAccessCode) { $command += ' --rotate-access-code' }
    if ($ApkPath) { $command += ' --app-download' }
    & ssh -o BatchMode=yes $PiHost $command
    if ($LASTEXITCODE -ne 0) { throw 'Installation failed; inspect Pi output' }
}
