# Build the site: compile the codec to WebAssembly and drop it next to the page.
#
#   powershell -ExecutionPolicy Bypass -File site\build.ps1
#   powershell -ExecutionPolicy Bypass -File site\build.ps1 -Serve   # + local server
param(
    [switch]$Serve,
    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$crate = Join-Path (Split-Path $here -Parent) 'wasm'

Write-Host '== rust -> wasm32-unknown-unknown'
Push-Location $crate
try {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & cargo build --release --target wasm32-unknown-unknown *> (Join-Path $env:TEMP 'mtc-wasm-build.log')
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($code -ne 0) {
        Get-Content (Join-Path $env:TEMP 'mtc-wasm-build.log') | Select-Object -Last 25
        throw 'cargo build --target wasm32-unknown-unknown failed'
    }
} finally {
    Pop-Location
}

$built = Join-Path $crate 'target\wasm32-unknown-unknown\release\mtcwasm.wasm'
if (-not (Test-Path $built)) { throw "missing $built" }
Copy-Item $built (Join-Path $here 'mtc.wasm') -Force
$size = (Get-Item (Join-Path $here 'mtc.wasm')).Length
Write-Host ("wasm {0:N0} bytes -> site\mtc.wasm" -f $size)

if ($Serve) {
    $python = 'D:\python\python.exe'
    if (-not (Test-Path $python)) { $python = 'python' }
    Write-Host "serving http://127.0.0.1:$Port/  (ctrl-c to stop)"
    Push-Location $here
    try { & $python -m http.server $Port } finally { Pop-Location }
}
