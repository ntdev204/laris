# Installs `laris` on Windows: downloads the archive, checks the signature of the checksum list and the checksum of the
# archive, and only then puts laris.exe in place. Rendered by `cargo xtask dist scripts`.
#
#   $env:LARIS_VERSION      release to install (default: latest)
#   $env:LARIS_INSTALL_DIR  where laris.exe goes (default: %LOCALAPPDATA%\Programs\laris)
#   $env:LARIS_RELEASE_URL  another release address (the signature is still checked against the built-in key)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$ReleaseUrl = if ($env:LARIS_RELEASE_URL) { $env:LARIS_RELEASE_URL } else { '__LARIS_RELEASE_URL__' }
$Version = if ($env:LARIS_VERSION) { $env:LARIS_VERSION } else { 'latest' }
$InstallDir = if ($env:LARIS_INSTALL_DIR) { $env:LARIS_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA 'Programs\laris' }
$PublicKey = @'
__LARIS_RELEASE_PUBKEY__
'@

function Stop-Install([string]$Message) {
    [Console]::Error.WriteLine("laris install: $Message")
    exit 1
}

function Remove-LeadingZeros([byte[]]$Bytes) {
    $i = 0
    while ($i -lt $Bytes.Length - 1 -and $Bytes[$i] -eq 0) { $i++ }
    return [byte[]]$Bytes[$i..($Bytes.Length - 1)]
}

# The signature is ECDSA P-256 over SHA-256 in DER form (what `openssl dgst -sign` writes). .NET wants the
# IEEE P1363 form (r then s, 32 bytes each) and the key as a CNG blob, so both are converted here. This works in
# Windows PowerShell 5.1 and PowerShell 7.
function Test-Signature([byte[]]$Data, [byte[]]$Der, [string]$Pem) {
    $b64 = (($Pem -split "`n") | Where-Object { $_ -and ($_ -notmatch '^-----') }) -join ''
    $spki = [Convert]::FromBase64String($b64.Trim())
    if ($spki.Length -ne 91 -or $spki[26] -ne 4) { return $false }
    $blob = [byte[]]@(0x45, 0x43, 0x53, 0x31, 0x20, 0, 0, 0) + $spki[27..90]
    if ($Der.Length -lt 8 -or $Der[0] -ne 0x30 -or $Der[2] -ne 0x02) { return $false }
    $rLen = $Der[3]
    $r = $Der[4..(3 + $rLen)]
    if ($Der[4 + $rLen] -ne 0x02) { return $false }
    $sLen = $Der[5 + $rLen]
    $s = $Der[(6 + $rLen)..(5 + $rLen + $sLen)]
    $r = Remove-LeadingZeros $r
    $s = Remove-LeadingZeros $s
    if ($r.Count -gt 32 -or $s.Count -gt 32) { return $false }
    $rs = [byte[]]((@(0) * (32 - $r.Count)) + $r + (@(0) * (32 - $s.Count)) + $s)
    $key = [System.Security.Cryptography.CngKey]::Import($blob, [System.Security.Cryptography.CngKeyBlobFormat]::EccPublicBlob)
    $ecdsa = New-Object System.Security.Cryptography.ECDsaCng($key)
    try {
        return $ecdsa.VerifyData($Data, $rs, [System.Security.Cryptography.HashAlgorithmName]::SHA256)
    } finally {
        $ecdsa.Dispose()
    }
}

if ($ReleaseUrl -like '__LARIS*') { Stop-Install 'this script was not rendered for a release (cargo xtask dist scripts)' }
if ($ReleaseUrl -notlike 'https://*') { Stop-Install 'the release address must start with https://' }
if ($Version -match '[/\\]|\.\.') { Stop-Install "bad version: $Version" }

$arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
if ($arch -ne 'X64') { Stop-Install "no build for Windows $arch" }
$target = 'x86_64-pc-windows-msvc'
$archive = "laris-$target.zip"

$work = Join-Path ([IO.Path]::GetTempPath()) ("laris-install-" + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null
try {
    $base = $ReleaseUrl.TrimEnd('/') + "/$Version"
    Write-Host "Downloading laris $Version for $target"
    foreach ($name in @('SHA256SUMS', 'SHA256SUMS.sig', $archive)) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri "$base/$name" -OutFile (Join-Path $work $name)
        } catch {
            Stop-Install "cannot download $name from ${base}: $($_.Exception.Message)"
        }
    }

    $sums = [IO.File]::ReadAllBytes((Join-Path $work 'SHA256SUMS'))
    $sig = [IO.File]::ReadAllBytes((Join-Path $work 'SHA256SUMS.sig'))
    $good = $false
    try { $good = Test-Signature $sums $sig $PublicKey } catch { $good = $false }
    if (-not $good) { Stop-Install 'the signature of SHA256SUMS is not valid: nothing was installed' }

    $expected = $null
    foreach ($line in ([Text.Encoding]::UTF8.GetString($sums) -split "`n")) {
        $parts = $line.Trim() -split '\s+'
        if ($parts.Count -eq 2 -and $parts[1] -eq $archive) { $expected = $parts[0] }
    }
    if (-not $expected) { Stop-Install "$archive is not in the signed list: nothing was installed" }
    $actual = (Get-FileHash -Algorithm SHA256 -Path (Join-Path $work $archive)).Hash.ToLowerInvariant()
    if ($actual -ne $expected.ToLowerInvariant()) {
        Stop-Install "the checksum of $archive does not match the signed list: nothing was installed"
    }

    $unpacked = Join-Path $work 'unpacked'
    Expand-Archive -Path (Join-Path $work $archive) -DestinationPath $unpacked
    $members = @(Get-ChildItem -Path $unpacked -Recurse -Force)
    if ($members.Count -ne 1 -or $members[0].Name -ne 'laris.exe' -or $members[0].PSIsContainer) {
        Stop-Install 'the archive holds unexpected files: nothing was installed'
    }

    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    $new = Join-Path $InstallDir 'laris.exe.new'
    Copy-Item -Force -Path $members[0].FullName -Destination $new
    Move-Item -Force -Path $new -Destination (Join-Path $InstallDir 'laris.exe')

    Write-Host "Installed $(Join-Path $InstallDir 'laris.exe')"
    & (Join-Path $InstallDir 'laris.exe') --version
    if ($LASTEXITCODE -ne 0) { Stop-Install 'the installed binary does not start' }

    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $entries = @(($userPath -split ';') | Where-Object { $_ })
    if ($entries -notcontains $InstallDir) {
        [Environment]::SetEnvironmentVariable('Path', (($entries + $InstallDir) -join ';'), 'User')
        Write-Host "Added $InstallDir to your PATH; open a new terminal to use `laris`."
    }
} finally {
    Remove-Item -Recurse -Force -Path $work -ErrorAction SilentlyContinue
}
