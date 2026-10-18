param(
    [Parameter(Mandatory)][string]$Path,
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
if ($env:WINDOWS_SIGNING_THUMBPRINT -notmatch '^[A-Fa-f0-9]{40}$') {
    throw 'Production signing requires WINDOWS_SIGNING_THUMBPRINT for the intended publisher.'
}
$tool = Get-Command signtool.exe -ErrorAction SilentlyContinue
if ($tool) { $signTool = $tool.Source } else {
    $signTool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" |
        Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $signTool) { throw 'Install the Windows SDK SignTool on the signing/verification runner.' }
if (-not $VerifyOnly) {
    if ($env:WINDOWS_TIMESTAMP_URL -notmatch '^https?://[^\s"$]+$') {
        throw 'Production signing requires an RFC3161 WINDOWS_TIMESTAMP_URL.'
    }
    $certificate = Get-Item "Cert:\CurrentUser\My\$env:WINDOWS_SIGNING_THUMBPRINT" -ErrorAction Stop
    if (-not $certificate.HasPrivateKey) { throw 'Publisher certificate has no accessible private key.' }
    & $signTool sign '/sha1' $env:WINDOWS_SIGNING_THUMBPRINT '/fd' 'SHA256' `
        '/tr' $env:WINDOWS_TIMESTAMP_URL '/td' 'SHA256' $Path
    if ($LASTEXITCODE -ne 0) { throw 'Publisher signing or timestamping failed.' }
}
& $signTool verify '/pa' '/all' '/tw' $Path
if ($LASTEXITCODE -ne 0) { throw 'Windows publisher certificate-chain verification failed.' }
$signature = Get-AuthenticodeSignature -LiteralPath $Path
if ($signature.Status -ne 'Valid' -or
    $signature.SignerCertificate.Thumbprint -ne $env:WINDOWS_SIGNING_THUMBPRINT -or
    -not $signature.TimeStamperCertificate) {
    throw 'Expected publisher signature and trusted timestamp are required.'
}
