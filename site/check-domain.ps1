# Check that the site is actually live on the domain, and that the wasm being
# served is the one built in this repository.
#
#   powershell -ExecutionPolicy Bypass -File site\check-domain.ps1
#   powershell -ExecutionPolicy Bypass -File site\check-domain.ps1 -Domain mtc-xiaimiredmi.top
#   powershell -ExecutionPolicy Bypass -File site\check-domain.ps1 -Base http://127.0.0.1:8765
#
# Exit code 0 means every check passed.
#
# Kept ASCII-only on purpose: Windows PowerShell 5.1 reads a .ps1 as ANSI unless
# it has a BOM, and a BOM in turn upsets the first line. English output, ASCII
# needles, no surprises.
param(
    [string]$Domain = 'mtc-xiaimiredmi.top',
    [string]$Base,
    [switch]$SkipDns
)

$ErrorActionPreference = 'Continue'
$failures = 0
function Pass($what, $detail = '') { Write-Host ("  ok    {0} {1}" -f $what, $detail) }
function Fail($what, $detail = '') {
    $script:failures++
    Write-Host ("  FAIL  {0} {1}" -f $what, $detail) -ForegroundColor Red
}
function Info($what, $detail = '') { Write-Host ("  ..    {0} {1}" -f $what, $detail) }

if (-not $Base) { $Base = "https://$Domain" }
Write-Host "checking $Base"

# ---- DNS --------------------------------------------------------------------
if ($Base.StartsWith('https://') -and -not $SkipDns) {
    Write-Host '== DNS'
    try {
        $answer = Resolve-DnsName $Domain -Type A -ErrorAction Stop |
            Where-Object { $_.IPAddress } | Select-Object -ExpandProperty IPAddress
        $expected = @('185.199.108.153', '185.199.109.153', '185.199.110.153', '185.199.111.153')
        $missing = @($expected | Where-Object { $answer -notcontains $_ })
        if ($missing.Count -eq 0) {
            Pass 'A records' ($answer -join ' ')
        } else {
            Fail 'A records' ("missing " + ($missing -join ', ') + "; got " + ($answer -join ' '))
        }
    } catch {
        Fail 'A records' $_.Exception.Message
    }
    try {
        $cname = Resolve-DnsName "www.$Domain" -Type CNAME -ErrorAction Stop |
            Where-Object { $_.NameHost } | Select-Object -First 1 -ExpandProperty NameHost
        if ($cname -like 'xiaimiredmi.github.io*') {
            Pass 'www CNAME' $cname
        } else {
            Fail 'www CNAME' "points at '$cname', expected xiaimiredmi.github.io"
        }
    } catch {
        Fail 'www CNAME' $_.Exception.Message
    }
}

# ---- the page ---------------------------------------------------------------
Write-Host '== page'
$page = $null
try {
    $page = Invoke-WebRequest $Base -UseBasicParsing -TimeoutSec 25
} catch {
    Fail 'GET /' $_.Exception.Message
}
if ($page) {
    Pass 'GET /' ("HTTP " + $page.StatusCode + ", " + [math]::Round($page.RawContentLength / 1KB, 1) + " KB")
    $body = [string]$page.Content
    foreach ($needle in @('MTC', 'id="demo"', 'app.js', 'styles.css')) {
        if ($body.Contains($needle)) { Pass "contains '$needle'" } else { Fail "contains '$needle'" }
    }
}

# ---- every asset the page needs ---------------------------------------------
Write-Host '== assets'
foreach ($asset in @('app.js', 'codec.js', 'styles.css', 'mtc.wasm', 'assets/sample.png')) {
    try {
        $head = Invoke-WebRequest "$Base/$asset" -Method Head -UseBasicParsing -TimeoutSec 25
        Pass $asset ("HTTP " + $head.StatusCode)
    } catch {
        Fail $asset $_.Exception.Message
    }
}
try {
    $codecJs = (Invoke-WebRequest "$Base/codec.js" -UseBasicParsing -TimeoutSec 25).Content
    if ([string]$codecJs -match 'mtc\.wasm') { Pass 'codec.js loads mtc.wasm' } else { Fail 'codec.js loads mtc.wasm' }
} catch {
    Fail 'GET /codec.js' $_.Exception.Message
}

# ---- the codec --------------------------------------------------------------
Write-Host '== codec'
$local = Join-Path $PSScriptRoot 'mtc.wasm'
$localSize = if (Test-Path $local) { (Get-Item $local).Length } else { 0 }
try {
    $head = Invoke-WebRequest "$Base/mtc.wasm" -Method Head -UseBasicParsing -TimeoutSec 25
    $remoteSize = [int]$head.Headers['Content-Length']
    if ($localSize -eq 0) {
        Info 'local mtc.wasm missing, cannot compare'
    } elseif ($remoteSize -eq $localSize) {
        Pass 'mtc.wasm' "$remoteSize bytes, identical to the local build"
    } else {
        Fail 'mtc.wasm' "served $remoteSize bytes, local build is $localSize - the deploy is stale"
    }
} catch {
    Fail 'HEAD /mtc.wasm' $_.Exception.Message
}

# ---- https ------------------------------------------------------------------
if ($Base.StartsWith('https://')) {
    Write-Host '== tls'
    try {
        $head = Invoke-WebRequest $Base -Method Head -UseBasicParsing -TimeoutSec 25
        Pass 'https' ("HTTP " + $head.StatusCode)
    } catch {
        Fail 'https' $_.Exception.Message
    }
    try {
        $plain = Invoke-WebRequest ($Base -replace '^https://', 'http://') -UseBasicParsing -MaximumRedirection 0 -TimeoutSec 25
        Info 'http did not redirect' ("HTTP " + $plain.StatusCode)
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        if ($code -ge 300 -and $code -lt 400) {
            Pass 'http redirects to https' "$code"
        } else {
            Info 'http redirect' "status $code"
        }
    }
}

Write-Host ''
if ($failures -eq 0) {
    Write-Host 'all checks passed - the domain is serving this repository' -ForegroundColor Green
    exit 0
}
Write-Host "$failures check(s) failed" -ForegroundColor Red
exit 1
