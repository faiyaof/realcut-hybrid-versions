[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RuntimePath,
    [Parameter(Mandatory = $true)]
    [string]$AllowedParent
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$runtime = (Resolve-Path -LiteralPath $RuntimePath).Path.TrimEnd('\')
$parent = (Resolve-Path -LiteralPath $AllowedParent).Path.TrimEnd('\')
if (-not $runtime.StartsWith($parent + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "Runtime must be inside the allowed package directory: $runtime"
}

function Get-TreeBytes([string]$Path) {
    $measure = Get-ChildItem -LiteralPath $Path -Recurse -File | Measure-Object Length -Sum
    if ($null -eq $measure.Sum) {
        return [int64]0
    }
    return [int64]$measure.Sum
}

function Remove-RuntimeItem([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    if (-not $resolved.StartsWith($runtime + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing removal outside the packaged Python runtime: $resolved"
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}

$before = Get-TreeBytes $runtime
$sitePackages = Join-Path $runtime "Lib\site-packages"

# Development-only Python files. RealCut loads Lib, DLLs and site-packages at runtime.
foreach ($name in @("Doc", "include", "libs", "tcl")) {
    Remove-RuntimeItem (Join-Path $runtime $name)
}

# These packages came from the workstation environment and are not used by RealCut.
$unusedPackagePattern = '^(PySide6|PyQt5|playwright|selenium|diffusers|onnxruntime|opencv|cv2|shiboken6)(-|_|$)'
Get-ChildItem -LiteralPath $sitePackages -Force |
    Where-Object { $_.Name -match $unusedPackagePattern } |
    ForEach-Object { Remove-RuntimeItem $_.FullName }

# PyTorch wheels include C/C++ extension headers and static link libraries. FunASR only
# needs the Python modules, PYD files and DLLs for inference.
Remove-RuntimeItem (Join-Path $sitePackages "torch\include")
$torchLib = Join-Path $sitePackages "torch\lib"
if (Test-Path -LiteralPath $torchLib) {
    Get-ChildItem -LiteralPath $torchLib -File -Filter "*.lib" | ForEach-Object {
        Remove-RuntimeItem $_.FullName
    }
}

# Source files remain available; bytecode is regenerated on first import.
Get-ChildItem -LiteralPath $runtime -Recurse -Directory -Filter "__pycache__" |
    Sort-Object FullName -Descending |
    ForEach-Object { Remove-RuntimeItem $_.FullName }

$after = Get-TreeBytes $runtime
$saved = $before - $after
Write-Host ("Optimized Python runtime: {0:N2} GiB -> {1:N2} GiB (saved {2:N2} GiB)" -f ($before / 1GB), ($after / 1GB), ($saved / 1GB))
