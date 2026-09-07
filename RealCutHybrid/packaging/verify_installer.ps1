[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerDirectory,
    [switch]$RequireSignature
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$directory = (Resolve-Path -LiteralPath $InstallerDirectory).Path
$manifestPath = Join-Path $directory "SHA256SUMS.txt"
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Missing checksum manifest: $manifestPath"
}

$expected = [Collections.Generic.Dictionary[string, string]]::new(
    [StringComparer]::OrdinalIgnoreCase
)
$lineNumber = 0
foreach ($line in Get-Content -LiteralPath $manifestPath -Encoding UTF8) {
    $lineNumber += 1
    if ([string]::IsNullOrWhiteSpace($line)) {
        continue
    }
    if ($line -notmatch '^(?<hash>[0-9a-fA-F]{64})[ \t]+(?<name>.+?)\s*$') {
        throw "Invalid checksum entry at line ${lineNumber}: $line"
    }
    $name = $Matches.name
    if (
        [IO.Path]::IsPathRooted($name) -or
        $name -in @(".", "..", "SHA256SUMS.txt") -or
        $name.Contains("\") -or
        $name.Contains("/")
    ) {
        throw "Unsafe or invalid checksum filename at line ${lineNumber}: $name"
    }
    if ($expected.ContainsKey($name)) {
        throw "Duplicate checksum entry at line ${lineNumber}: $name"
    }
    $expected.Add($name, $Matches.hash.ToLowerInvariant())
}

if ($expected.Count -eq 0) {
    throw "Checksum manifest is empty: $manifestPath"
}

$actualFiles = @(
    Get-ChildItem -LiteralPath $directory -File |
        Where-Object { $_.Name -ne "SHA256SUMS.txt" }
)
foreach ($file in $actualFiles) {
    if (-not $expected.ContainsKey($file.Name)) {
        throw "Unlisted file in installer directory: $($file.Name)"
    }
}

foreach ($entry in $expected.GetEnumerator()) {
    $path = Join-Path $directory $entry.Key
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Missing installer file: $($entry.Key)"
    }
    $actualHash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $entry.Value) {
        throw "SHA-256 mismatch: $($entry.Key)"
    }
}

$setupNames = @($expected.Keys | Where-Object { $_ -like "*-Setup.exe" })
if ($setupNames.Count -ne 1) {
    throw "Expected exactly one *-Setup.exe entry, found $($setupNames.Count)"
}

$setupPath = Join-Path $directory $setupNames[0]
$signature = Get-AuthenticodeSignature -LiteralPath $setupPath
if ($signature.Status -eq [Management.Automation.SignatureStatus]::Valid) {
    Write-Host "Authenticode: Valid ($($signature.SignerCertificate.Subject))"
} elseif ($RequireSignature) {
    throw "Authenticode signature is required but status is $($signature.Status): $($signature.StatusMessage)"
} else {
    Write-Warning "Authenticode status is $($signature.Status). Hashes are valid, but SmartScreen may warn."
}

Write-Host "Verified $($expected.Count) files against $manifestPath"
[pscustomobject]@{
    InstallerDirectory = $directory
    FileCount = $expected.Count
    SetupFile = $setupNames[0]
    SignatureStatus = [string]$signature.Status
}
