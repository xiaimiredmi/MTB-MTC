# Build the MTC camera/gallery APK without Gradle.
#
# Everything needed is already on this machine: the Android SDK build-tools for
# aapt2 / d8 / zipalign / apksigner, platform android-34 for android.jar, the NDK
# for the Rust cross-build, and cargo-ndk to drive it. No Maven, no Gradle, no
# network, so a build is reproducible and quick.
#
#   powershell -ExecutionPolicy Bypass -File android\build.ps1
#   powershell -ExecutionPolicy Bypass -File android\build.ps1 -Install
#   powershell -ExecutionPolicy Bypass -File android\build.ps1 -Abis arm64-v8a,armeabi-v7a
param(
    [switch]$Install,
    [string]$Sdk = 'D:\Android\sdk',
    [string]$Ndk = 'D:\Android\android-ndk-r29',
    [string]$BuildTools = '36.1.0',
    [string]$Platform = 'android-34',
    [string[]]$Abis = @('arm64-v8a')
)

$ErrorActionPreference = 'Stop'
$env:JAVA_TOOL_OPTIONS = '-Duser.language=en -Duser.country=US'

$here = $PSScriptRoot
$src = Join-Path $here 'app\src\main'
$build = Join-Path $here 'build'
$gen = Join-Path $build 'gen'
$classes = Join-Path $build 'classes'
$dex = Join-Path $build 'dex'
$bt = Join-Path $Sdk "build-tools\$BuildTools"
$androidJar = Join-Path $Sdk "platforms\$Platform\android.jar"

foreach ($tool in @('aapt2.exe', 'd8.bat', 'zipalign.exe', 'apksigner.bat')) {
    if (-not (Test-Path (Join-Path $bt $tool))) { throw "missing $tool in $bt" }
}
if (-not (Test-Path $androidJar)) { throw "missing $androidJar" }

# Native tools write progress to stderr; PowerShell turns that into a terminating
# error under Stop. Send everything to a log and decide on the exit code.
function Invoke-Tool([string]$label, [string]$exe, [string[]]$toolArgs) {
    $log = Join-Path $build "$label.log"
    # PowerShell 5.1 turns a native command's stderr into a terminating error when
    # the preference is Stop, even when it is redirected. Scope it down here.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $exe @toolArgs *> $log
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($code -ne 0) {
        Write-Host "--- $label failed (exit $code) ---"
        Get-Content $log -ErrorAction SilentlyContinue | Select-Object -Last 40
        throw "$label failed"
    }
    return $log
}

New-Item -ItemType Directory -Force $build, $gen, $classes, $dex | Out-Null
Get-ChildItem $build -Recurse -File -ErrorAction SilentlyContinue | Remove-Item -Force

# --- 1. the codec, as a shared library per ABI -------------------------------
Write-Host "== rust: $($Abis -join ', ')"
$env:ANDROID_NDK_HOME = $Ndk
Push-Location (Join-Path $here 'jni')
try {
    $targetArgs = @()
    foreach ($abi in $Abis) { $targetArgs += @('-t', $abi) }
    $cargoArgs = $targetArgs + @('-o', (Join-Path $src 'jniLibs'), 'build', '--release')
    Invoke-Tool 'cargo' 'cargo' (@('ndk') + $cargoArgs) | Out-Null
} finally {
    Pop-Location
}

# --- 2. resources and the manifest ------------------------------------------
Write-Host '== aapt2'
$flat = Join-Path $build 'flat'
New-Item -ItemType Directory -Force $flat | Out-Null
Invoke-Tool 'aapt2-compile' (Join-Path $bt 'aapt2.exe') @('compile', '--dir', (Join-Path $src 'res'), '-o', $flat) | Out-Null

$apkUnsigned = Join-Path $build 'unsigned.apk'
$flatFiles = Get-ChildItem $flat -Filter '*.flat' | ForEach-Object { $_.FullName }
$linkArgs = @(
    'link', '-o', $apkUnsigned,
    '-I', $androidJar,
    '--manifest', (Join-Path $src 'AndroidManifest.xml'),
    '--java', $gen,
    '--min-sdk-version', '24',
    '--target-sdk-version', '34',
    '--version-code', '1',
    '--version-name', '0.1'
) + $flatFiles
Invoke-Tool 'aapt2-link' (Join-Path $bt 'aapt2.exe') $linkArgs | Out-Null

# --- 3. java ----------------------------------------------------------------
Write-Host '== javac'
$java = @(Get-ChildItem -Path (Join-Path $src 'java'), $gen -Recurse -Filter '*.java' |
    ForEach-Object { $_.FullName })
$javacArgs = @('-source', '8', '-target', '8', '-Xlint:-options',
    '-bootclasspath', $androidJar, '-d', $classes, '-encoding', 'UTF-8') + $java
Invoke-Tool 'javac' 'javac' $javacArgs | Out-Null

# --- 4. dex -----------------------------------------------------------------
Write-Host '== d8'
$classFiles = @(Get-ChildItem $classes -Recurse -Filter '*.class' |
    ForEach-Object { $_.FullName })
$d8Args = @('--release', '--min-api', '24', '--lib', $androidJar, '--output', $dex) + $classFiles
Invoke-Tool 'd8' (Join-Path $bt 'd8.bat') $d8Args | Out-Null

# --- 5. pack ----------------------------------------------------------------
Write-Host '== package'
$packed = Join-Path $build 'packed.apk'
Copy-Item $apkUnsigned $packed -Force
Add-Type -AssemblyName System.IO.Compression.FileSystem
Add-Type -AssemblyName System.IO.Compression

function Add-ApkEntry([string]$apkPath, [string]$entry, [string]$file) {
    $zip = [System.IO.Compression.ZipFile]::Open($apkPath, 'Update')
    try {
        $old = $zip.GetEntry($entry)
        if ($old) { $old.Delete() }
        [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $zip, $file, $entry,
            [System.IO.Compression.CompressionLevel]::Optimal)
    } finally {
        $zip.Dispose()
    }
}

Add-ApkEntry $packed 'classes.dex' (Join-Path $dex 'classes.dex')
foreach ($abi in $Abis) {
    $so = Join-Path $src "jniLibs\$abi\libmtcjni.so"
    if (-not (Test-Path $so)) { throw "missing $so" }
    Add-ApkEntry $packed "lib/$abi/libmtcjni.so" $so
}

# --- 6. align and sign ------------------------------------------------------
Write-Host '== zipalign / apksigner'
$aligned = Join-Path $build 'aligned.apk'
Invoke-Tool 'zipalign' (Join-Path $bt 'zipalign.exe') @('-f', '-p', '4', $packed, $aligned) | Out-Null

$ks = Join-Path $env:USERPROFILE '.android\debug.keystore'
if (-not (Test-Path $ks)) {
    New-Item -ItemType Directory -Force (Split-Path $ks) | Out-Null
    Invoke-Tool 'keytool' 'keytool' @(
        '-genkeypair', '-keystore', $ks, '-storepass', 'android', '-keypass', 'android',
        '-alias', 'androiddebugkey', '-keyalg', 'RSA', '-keysize', '2048',
        '-validity', '10000', '-dname', 'CN=Android Debug,O=Android,C=US'
    ) | Out-Null
}

$apk = Join-Path $here 'mtc-camera.apk'
Invoke-Tool 'apksigner' (Join-Path $bt 'apksigner.bat') @(
    'sign', '--ks', $ks, '--ks-pass', 'pass:android',
    '--ks-key-alias', 'androiddebugkey', '--out', $apk, $aligned
) | Out-Null
Invoke-Tool 'apksigner-verify' (Join-Path $bt 'apksigner.bat') @(
    'verify', '--print-certs', $apk
) | Out-Null

$size = (Get-Item $apk).Length
Write-Host ''
Write-Host ('built {0} ({1:N1} MB) for {2}' -f $apk, ($size / 1MB), ($Abis -join ', '))

if ($Install) {
    Invoke-Tool 'adb-install' 'adb' @('install', '-r', $apk) | Out-Null
    Write-Host 'installed'
}
