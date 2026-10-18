param(
    [Parameter(Mandatory)][string]$Version,
    [Parameter(Mandatory)][ValidatePattern('^[a-f0-9]{40}$')][string]$SourceRevision,
    [ValidateSet('development', 'production')][string]$Mode = 'development',
    [string]$Output = 'dist',
    [string]$Compiler = "$env:LOCALAPPDATA\GraveTrailBuildTools\ISCC.exe"
)
$ErrorActionPreference = 'Stop'
if ($Version -notmatch '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$') { throw 'Invalid release version.' }
foreach ($part in $Version.Split('.')) {
    if ([long]$part -gt 65535) { throw 'Version exceeds Windows version metadata limits.' }
}
$outputPath = (Resolve-Path -LiteralPath $Output).Path
$bundle = Join-Path $outputPath '.build\bundle\gravetrail'
$application = Join-Path $bundle 'gravetrail.exe'
if (-not (Test-Path -LiteralPath $application)) { throw 'Build the complete Windows executable bundle first.' }
$compileArgs = @("/DVersion=$Version", "/DBundle=$bundle", "/DOutput=$outputPath")
if ($Mode -eq 'production') {
    if (-not $env:WINDOWS_PUBLISHER) { throw 'WINDOWS_PUBLISHER is required for production metadata.' }
    & "$PSScriptRoot\sign_windows.ps1" -Path $application
    $signScript = "$PSScriptRoot\sign_windows.ps1"
    $compileArgs += @('/DProduction', "/DPublisher=$env:WINDOWS_PUBLISHER",
        "/Sgravetrail=pwsh.exe -NoProfile -NonInteractive -File `$q$signScript`$q -Path `$f")
}
# Inventory every native dependency; preserve third-party signatures and hash the complete payload.
$inventory = @(Get-ChildItem -LiteralPath $bundle -Recurse -File | ForEach-Object {
    $record = @{path = [IO.Path]::GetRelativePath($bundle, $_.FullName).Replace('\', '/');
                sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
    if ($_.Extension -in @('.exe', '.dll', '.pyd')) {
        $signature = Get-AuthenticodeSignature -LiteralPath $_.FullName
        $record.signature = $signature.Status.ToString()
        if ($signature.SignerCertificate -and $signature.Status -ne 'Valid') {
            throw "Invalid dependency signature: $($record.path)"
        }
    }
    $record
})
& $Compiler @compileArgs "$PSScriptRoot\windows.iss"
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup installer compilation failed.' }
$suffix = if ($Mode -eq 'production') { '' } else { '-unsigned' }
$installer = "gravetrail-$Version-windows-amd64-setup$suffix.exe"
if ($Mode -eq 'production') { & "$PSScriptRoot\sign_windows.ps1" -Path (Join-Path $outputPath $installer) -VerifyOnly }
# Recreate portable bytes after signing, before final checksums.
uv run --locked python -c "import shutil,sys; shutil.make_archive(sys.argv[1], 'zip', sys.argv[2], 'gravetrail')" `
    (Join-Path $outputPath "gravetrail-$Version-windows-amd64") (Split-Path $bundle)
if ($LASTEXITCODE -ne 0) { throw 'Portable ZIP generation failed.' }
@{version = $Version; source_revision = $SourceRevision; platform = 'windows'; architecture = 'amd64';
  mode = $Mode; signing_status = $(if ($Mode -eq 'production') { 'signed' } else { 'unsigned' });
  installer = $installer; lifecycle_verified = $false; payload = $inventory;
  toolchain = @{inno_setup = '7.1.0'; os = [Environment]::OSVersion.VersionString};
  publisher_thumbprint = $(if ($Mode -eq 'production') { $env:WINDOWS_SIGNING_THUMBPRINT } else { $null })} |
    ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $outputPath 'windows-verification.json') -Encoding utf8
