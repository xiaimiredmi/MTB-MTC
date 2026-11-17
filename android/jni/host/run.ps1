# Run the JNI smoke test on the desktop JVM.
#
# Builds android/jni for this machine (a DLL on Windows), compiles the host copies
# of the two Java classes, and drives the same four native entry points the phone
# uses. This is how the JNI surface gets checked without a device.
#
#   powershell -ExecutionPolicy Bypass -File android\jni\host\run.ps1
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$jni = Split-Path $here -Parent
$out = Join-Path $jni 'target\host-classes'

Write-Host '== rust (host)'
Push-Location $jni
try {
    # cargo writes progress to stderr; PowerShell would treat that as fatal under Stop.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & cargo build --release *> (Join-Path $env:TEMP 'mtcjni-host-build.log')
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($code -ne 0) {
        Get-Content (Join-Path $env:TEMP 'mtcjni-host-build.log') | Select-Object -Last 20
        throw 'cargo build failed'
    }
} finally {
    Pop-Location
}

$lib = Join-Path $jni 'target\release'
if ($IsWindows -or $env:OS -eq 'Windows_NT') {
    $libName = 'mtcjni.dll'
} elseif ($env:OS -eq 'Darwin' -or $IsMacOS) {
    $libName = 'libmtcjni.dylib'
} else {
    $libName = 'libmtcjni.so'
}
if (-not (Test-Path (Join-Path $lib $libName))) { throw "missing $libName in $lib" }

Write-Host '== javac'
New-Item -ItemType Directory -Force $out | Out-Null
Get-ChildItem $out -Recurse -File -ErrorAction SilentlyContinue | Remove-Item -Force
$sources = @(
    (Join-Path $here 'dev\mtc\Mtc.java'),
    (Join-Path $here 'Smoke.java')
)
& javac -d $out -encoding UTF-8 @sources
if ($LASTEXITCODE -ne 0) { throw 'javac failed' }

Write-Host '== java'
Push-Location $out
try {
    & java "-Djava.library.path=$lib" dev.mtc.Smoke
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($code -ne 0) { throw "smoke test failed (exit $code)" }
Write-Host "ok"
