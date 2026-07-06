param(
    [string]$Python = "python",
    [string]$BuildName = "mesh_convert_gui",
    [string]$WorkName = ""
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EntryPoint = Join-Path $PSScriptRoot "mesh_convert_gui_entry.py"
$DistPath = Join-Path $ProjectRoot "dist"
$BuildRoot = Join-Path $ProjectRoot "build"
if (-not $WorkName) {
    $WorkName = $BuildName
}
$WorkRoot = Join-Path $BuildRoot $WorkName
$WorkPath = Join-Path $WorkRoot "work"
$SpecPath = Join-Path $WorkRoot "spec"
$OutputPath = Join-Path $DistPath $BuildName
$ExePath = Join-Path $OutputPath "$BuildName.exe"

foreach ($Path in @($WorkRoot, $OutputPath)) {
    if (Test-Path -LiteralPath $Path) {
        throw "Build output already exists: $Path. This script will not delete or overwrite it. Choose a different -BuildName/-WorkName or manually clean the exact path."
    }
}

Write-Host "Checking PyInstaller..."
& $Python -m PyInstaller --version
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not installed. Install it with: $Python -m pip install pyinstaller"
}

Write-Host "Building $BuildName.exe..."
& $Python -m PyInstaller `
    --windowed `
    --name $BuildName `
    --distpath $DistPath `
    --workpath $WorkPath `
    --specpath $SpecPath `
    --collect-all gmsh `
    $EntryPoint

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed while building $BuildName.exe."
}

Write-Host "Built: $ExePath"
