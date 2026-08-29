[CmdletBinding()]
param(
    [string]$RuntimeSource = "",
    [string]$Version = (Get-Date -Format "yyyy.MM.dd"),
    [switch]$SkipCompile,
    [switch]$SkipInstaller,
    [switch]$SkipHashes,
    [switch]$SkipRuntimeOptimization
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$WorkspaceRoot = (Resolve-Path (Join-Path $ProjectRoot "..")).Path
if (-not $RuntimeSource) {
    $RuntimeSource = Join-Path $WorkspaceRoot "RealCutHybrid_Deploy_20260826"
}
$RuntimeSource = (Resolve-Path $RuntimeSource).Path

$BuildRoot = Join-Path $ProjectRoot "build\handover"
$NuitkaOutput = Join-Path $BuildRoot "nuitka"
$PackageRoot = Join-Path $ProjectRoot ("dist\RealCutHybrid-Handover-{0}" -f $Version)
$InstallerOutput = Join-Path $ProjectRoot "dist\installer"
$Python = Join-Path $ProjectRoot ".venv-build\Scripts\python.exe"
$ScriptRoot = Join-Path $ProjectRoot "vendor\experimental\scripts"
$EntryPointStaging = Join-Path $BuildRoot "entrypoints"

function Assert-ChildPath([string]$Path, [string]$Parent) {
    $fullPath = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $fullParent = [IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    if (-not $fullPath.StartsWith($fullParent, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing operation outside expected directory: $fullPath"
    }
}

function Reset-Directory([string]$Path, [string]$Parent) {
    Assert-ChildPath $Path $Parent
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Copy-Tree([string]$Source, [string]$Destination) {
    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        throw "Missing source directory: $Source"
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    & robocopy.exe $Source $Destination /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NJH /NJS /NP
    if ($LASTEXITCODE -gt 7) {
        throw "Robocopy failed ($LASTEXITCODE): $Source"
    }
}

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    python -m venv --system-site-packages (Join-Path $ProjectRoot ".venv-build")
    & $Python -m pip install "Nuitka==4.2" ordered-set zstandard
}

$binaryAliases = @{
    "mirror_通用" = "mirror_general"
    "导入视频到剪映" = "step_01_import"
    "步骤2-分离音频" = "step_02_separate_audio"
    "步骤3-FunASR" = "step_03_funasr"
    "步骤4-切割排序" = "step_04_select_sort"
    "步骤4后-开盒补位" = "step_04_open_box"
    "步骤5-淡入淡出" = "step_05_fade"
    "步骤6-画面匹配" = "step_06_visual_match"
    "步骤7-生成字幕" = "step_07_subtitles"
    "步骤8-转场特效" = "step_08_transitions"
    "步骤9-花字音效" = "step_09_flower_sfx"
    "步骤10-添加BGM" = "step_10_bgm"
    "步骤11-添加水印" = "step_11_watermark"
    "步骤12-字体样式" = "step_12_style"
    "导入字幕" = "import_subtitles"
}
New-Item -ItemType Directory -Force -Path $BuildRoot | Out-Null
Reset-Directory $EntryPointStaging $BuildRoot

$entryPoints = @(
    [pscustomobject]@{ Path = (Join-Path $ProjectRoot "web_server.py"); CompilePath = (Join-Path $ProjectRoot "web_server.py"); Name = "web_server" },
    [pscustomobject]@{ Path = (Join-Path $ProjectRoot "realcut_hybrid.py"); CompilePath = (Join-Path $ProjectRoot "realcut_hybrid.py"); Name = "realcut_hybrid" }
)
$entryPoints += Get-ChildItem -LiteralPath $ScriptRoot -Filter "*.py" -File |
    Where-Object { -not $_.BaseName.StartsWith("_") } |
    Sort-Object Name |
    ForEach-Object {
        $name = if ($binaryAliases.ContainsKey($_.BaseName)) { $binaryAliases[$_.BaseName] } else { $_.BaseName }
        $compilePath = $_.FullName
        if ($name -ne $_.BaseName) {
            $compilePath = Join-Path $EntryPointStaging ($name + ".py")
            Copy-Item -LiteralPath $_.FullName -Destination $compilePath -Force
        }
        [pscustomobject]@{ Path = $_.FullName; CompilePath = $compilePath; Name = $name }
    }

if (-not $SkipCompile) {
    Reset-Directory $NuitkaOutput $BuildRoot
    $env:PYTHONPATH = "$ProjectRoot;$ScriptRoot"
    $nuitkaArgs = @(
        "-m", "nuitka",
        "--mode=standalone",
        "--mingw64",
        "--assume-yes-for-downloads",
        "--output-dir=$NuitkaOutput"
    )
    foreach ($entry in $entryPoints) {
        $nuitkaArgs += "--main=$($entry.CompilePath)"
    }
    & $Python @nuitkaArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Nuitka compilation failed with exit code $LASTEXITCODE"
    }
}

$CompiledDist = Join-Path $NuitkaOutput "web_server.dist"
$PrimaryExe = Join-Path $CompiledDist "web_server.exe"
if (-not (Test-Path -LiteralPath $PrimaryExe -PathType Leaf)) {
    throw "Compiled multidist launcher not found: $PrimaryExe"
}

Reset-Directory $PackageRoot (Join-Path $ProjectRoot "dist")
$BinDir = Join-Path $PackageRoot "bin"
Copy-Tree $CompiledDist $BinDir
foreach ($entry in $entryPoints) {
    $target = Join-Path $BinDir ($entry.Name + ".exe")
    if ($entry.Name -ne "web_server") {
        Copy-Item -LiteralPath (Join-Path $BinDir "web_server.exe") -Destination $target -Force
    }
}

foreach ($name in @("runtime", "models_cache", "assets")) {
    Copy-Tree (Join-Path $RuntimeSource $name) (Join-Path $PackageRoot $name)
}
if (-not $SkipRuntimeOptimization) {
    & (Join-Path $PSScriptRoot "optimize_python_runtime.ps1") `
        -RuntimePath (Join-Path $PackageRoot "runtime\python") `
        -AllowedParent $PackageRoot
}
Copy-Tree (Join-Path $ProjectRoot "web") (Join-Path $PackageRoot "web")
Copy-Tree (Join-Path $ProjectRoot "config") (Join-Path $PackageRoot "config")

$ScriptDataDir = Join-Path $PackageRoot "vendor\experimental\scripts"
New-Item -ItemType Directory -Force -Path $ScriptDataDir | Out-Null
Copy-Item -LiteralPath (Join-Path $ScriptRoot "transitions_template.json") -Destination $ScriptDataDir -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "deploy_env.bat") -Destination (Join-Path $PackageRoot "config\deploy_env.bat") -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "Start-RealCutHybridWeb.bat") -Destination $PackageRoot -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "README_HANDOVER.md") -Destination (Join-Path $PackageRoot "README.md") -Force

foreach ($name in @("state", "logs", "reports", "snapshots", "manifests", "runs")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $PackageRoot $name) | Out-Null
}

$forbidden = @(
    "realcut_hybrid.py", "web_server.py", "postprocess.py", "manifest.py", "runtime_layout.py",
    "runtime_settings.py"
)
foreach ($name in $forbidden) {
    if (Test-Path -LiteralPath (Join-Path $PackageRoot $name)) {
        throw "Source leak detected in package: $name"
    }
}
if (Get-ChildItem -LiteralPath $ScriptDataDir -Filter "*.py" -File -ErrorAction SilentlyContinue) {
    throw "Source leak detected under vendor\experimental\scripts"
}

if (-not $SkipHashes) {
    $HashFile = Join-Path $PackageRoot "SHA256SUMS.txt"
    $lines = Get-ChildItem -LiteralPath $PackageRoot -Recurse -File |
        Where-Object { $_.FullName -ne $HashFile } |
        Sort-Object FullName |
        ForEach-Object {
            $relative = $_.FullName.Substring($PackageRoot.Length + 1).Replace('\', '/')
            $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            "$hash  $relative"
        }
    [IO.File]::WriteAllLines($HashFile, $lines, [Text.UTF8Encoding]::new($false))
}

$env:REALCUT_ROOT = $PackageRoot
$env:REALCUT_BIN_DIR = $BinDir
$env:REALCUT_PYTHON_RUNTIME = Join-Path $PackageRoot "runtime\python"
$env:REALCUT_MODELSCOPE_CACHE = Join-Path $PackageRoot "models_cache"
$env:MODELSCOPE_CACHE = $env:REALCUT_MODELSCOPE_CACHE
$env:REALCUT_SCRIPT_DATA_DIR = $ScriptDataDir
$env:REALCUT_ASSETS_ROOT = Join-Path $PackageRoot "assets"
$env:REALCUT_STYLE_LIB = Join-Path $PackageRoot "assets\styles"
$env:REALCUT_KEYWORD_FILE = Join-Path $PackageRoot "config\highlight_keywords.txt"
$env:REALCUT_JIANYING_EXE = Join-Path $PackageRoot "runtime\JianyingPro\5.9.0.11632\JianyingPro.exe"
$env:OFFICECLI_BIN = Join-Path $PackageRoot "runtime\officecli\officecli.exe"
$env:PATH = (Join-Path $PackageRoot "runtime\ffmpeg") + ";" + $env:PATH
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

& (Join-Path $BinDir "realcut_hybrid.exe") check
if ($LASTEXITCODE -ne 0) {
    throw "Packaged environment check failed with exit code $LASTEXITCODE"
}

if (-not $SkipInstaller) {
    $isccCandidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    )
    $iscc = $isccCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if (-not $iscc) {
        $command = Get-Command iscc.exe -ErrorAction SilentlyContinue
        if ($command) { $iscc = $command.Source }
    }
    if (-not $iscc) {
        throw "Inno Setup 6 was not found. Install it or use -SkipInstaller."
    }
    Reset-Directory $InstallerOutput (Join-Path $ProjectRoot "dist")
    $substLetter = @("R", "S", "T", "U") |
        Where-Object { -not (Get-PSDrive $_ -ErrorAction SilentlyContinue) } |
        Select-Object -First 1
    if (-not $substLetter) {
        throw "No free drive letter is available for the short Inno source path."
    }
    & subst.exe "${substLetter}:" $PackageRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create temporary ${substLetter}: drive."
    }
    try {
        & $iscc "/DSourceDir=${substLetter}:" "/DOutputDir=$InstallerOutput" "/DAppVersion=$Version" (Join-Path $PSScriptRoot "RealCutHybrid.iss")
        if ($LASTEXITCODE -ne 0) {
            throw "Inno Setup failed with exit code $LASTEXITCODE"
        }
    } finally {
        & subst.exe "${substLetter}:" /D
    }
    $installerHashFile = Join-Path $InstallerOutput "SHA256SUMS.txt"
    $installerHashes = Get-ChildItem -LiteralPath $InstallerOutput -File |
        Where-Object { $_.FullName -ne $installerHashFile } |
        Sort-Object Name |
        ForEach-Object {
            $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            "$hash  $($_.Name)"
        }
    [IO.File]::WriteAllLines($installerHashFile, $installerHashes, [Text.UTF8Encoding]::new($false))
}

Write-Host "Handover package: $PackageRoot"
if (-not $SkipInstaller) {
    Write-Host "Installer output: $InstallerOutput"
}
