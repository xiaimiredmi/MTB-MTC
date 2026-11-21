 Push site/ to a server over SSH.
#
# Packs the directory into one tar and copies it in a single connection, then
# unpacks it on the far side — much faster than copying a hundred small files, and
# it keeps the wasm and the page in the same generation.
#
#   powershell -ExecutionPolicy Bypass -File site\deploy.ps1 -Server 1.2.3.4
#   powershell -ExecutionPolicy Bypass -File site\deploy.ps1 -Server 1.2.3.4 -User ubuntu -Path /var/www/mtc
#   powershell -ExecutionPolicy Bypass -File site\deploy.ps1 -Server 1.2.3.4 -DryRun
#
# Needs the OpenSSH client that ships with Windows 10/11 (`ssh`, `scp`). Key-based
# login is assumed; if it asks for a password, that is fine too, but then it will
# ask twice (once per command).
param(
    [Parameter(Mandatory = $true)][string]$Server,
    [string]$User = 'root',
    [string]$Path = '/var/www/mtc',
    [string]$Key,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$site = $PSScriptRoot
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$tar = Join-Path $env:TEMP "mtc-site-$stamp.tar.gz"

foreach ($tool in 'ssh', 'scp') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "$tool not found; install the OpenSSH client (Windows optional feature)"
    }
}
if (-not (Test-Path (Join-Path $site 'index.html'))) { throw "no index.html in $site" }

$sshArgs = @()
$scpArgs = @()
if ($Key) {
    $sshArgs += @('-i', $Key)
    $scpArgs += @('-i', $Key)
}
$sshArgs += @('-o', 'StrictHostKeyChecking=accept-new')
$scpArgs += @('-o', 'StrictHostKeyChecking=accept-new')

Write-Host "== packing $site"
Push-Location $site
try {
    & tar -czf $tar --exclude=build --exclude=deploy.ps1 *
    if ($LASTEXITCODE -ne 0) { throw 'tar failed' }
} finally {
    Pop-Location
}
$size = (Get-Item $tar).Length
Write-Host ("   {0:N1} KB -> {1}" -f ($size / 1KB), $tar)

$remote = "$User@$Server"
Write-Host "== uploading to ${remote}:$Path"
if ($DryRun) {
    Write-Host "   would run: scp $($scpArgs -join ' ') $tar ${remote}:/tmp/"
    Write-Host "   would run: ssh ... mkdir -p $Path && tar -xzf /tmp/$(Split-Path $tar -Leaf) -C $Path"
    Remove-Item $tar -Force
    return
}

& scp @scpArgs $tar "${remote}:/tmp/"
if ($LASTEXITCODE -ne 0) { throw 'scp failed' }

# mkdir, unpack over the old files, then tell nginx (harmless if it is not there).
$script = "set -e; sudo mkdir -p '$Path'; sudo tar -xzf '/tmp/$(Split-Path $tar -Leaf)' -C '$Path'; " +
          "sudo chown -R www-data:www-data '$Path' 2>/dev/null || true; " +
          "sudo nginx -t >/dev/null 2>&1 && sudo systemctl reload nginx || echo 'nginx: not reloaded'; " +
          "ls -la '$Path' | head -20"
Write-Host "== unpacking"
& ssh @sshArgs $remote $script
if ($LASTEXITCODE -ne 0) { throw 'remote unpack failed' }

Remove-Item $tar -Force
Write-Host ''
Write-Host "deployed. open https://$Server/ (or the domain, once DNS points here)"
