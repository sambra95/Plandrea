<#
Build the portable Windows folder for Plandrea.

Produces Plandrea\ carrying its own Python and every dependency, so the PC it
lands on needs no Python, uv or git - download, unzip, double-click Plandrea.cmd.
The app opens in your default browser and quits once the last tab closes.

Built for x64, on the machine running this script.

Usage:
  ./windows_install/make_dist.ps1 [-Version 1.0.0] [-NoZip]
#>
param([string]$Version = "1.0.0", [switch]$NoZip)

$ErrorActionPreference = "Stop"
$PyVersion = "3.12"
$Root = (Resolve-Path "$PSScriptRoot\..").Path
$App = "$Root\dist\Plandrea"
$Build = "$Root\build"
Set-Location $Root

function Step($text) { Write-Host "`n==> $text" }
function Size($path) { "{0:N0} MB" -f ((Get-ChildItem $path -Recurse -File |
    Measure-Object Length -Sum).Sum / 1MB) }

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv not found: https://docs.astral.sh/uv/"
}
Write-Host "Building Plandrea $Version for Windows (x64)"

Step "[1/6] Skeleton"
Remove-Item $App -Recurse -Force -ErrorAction SilentlyContinue
New-Item "$App\bin", $Build -ItemType Directory -Force | Out-Null

Step "[2/6] Bundling Python $PyVersion"
# A uv-managed (python-build-standalone) interpreter is relocatable. A `uv venv`
# would not do: it only symlinks back to the Python that made it.
uv python install $PyVersion 2>&1 | Out-Null
$src = Get-ChildItem (uv python dir) -Directory |
    Where-Object Name -like "cpython-$PyVersion.*-windows-x86_64-none" |
    Sort-Object Name | Select-Object -Last 1
if (-not $src) { throw "no CPython $PyVersion for x64; run: uv python install $PyVersion" }
Write-Host "    $($src.Name)"
# uv has kept the interpreter at the root of that folder and, in later versions,
# under install\ - so it is found rather than assumed.
$from = (Get-ChildItem $src.FullName -Recurse -Filter python.exe -Depth 1 |
    Select-Object -First 1).Directory
Copy-Item $from.FullName "$App\bin\python" -Recurse
# Installing into the copy is the whole point of having made one.
Get-ChildItem "$App\bin\python" -Recurse -Filter EXTERNALLY-MANAGED |
    Remove-Item -Force
$python = "$App\bin\python\python.exe"

Step "[3/6] Installing dependencies"
uv export --no-dev --no-emit-project -o "$Build\requirements.txt" | Out-Null
uv pip install --python $python -r "$Build\requirements.txt" --quiet
Write-Host "    $((Select-String '^[a-zA-Z0-9_.-]+==' "$Build\requirements.txt").Count) pinned packages"

Step "[4/6] Copying the app"
# Every module at the root, so adding one needs no edit here.
Copy-Item "$Root\*.py", "$Root\README.md" $App
Copy-Item "$Root\app_pages", "$Root\assets", "$Root\.streamlit" $App -Recurse
Get-ChildItem $App -Recurse -Directory -Filter __pycache__ |
    Remove-Item -Recurse -Force

Step "[5/6] Trimming"
# What a packaged Streamlit app never touches. What is absent here is equally
# deliberate: pyarrow's other libraries are linked by pyarrow.lib itself, and
# pydeck/nbextension/__init__.py is imported by pydeck - only its static/ can go.
$before = Size $App
$lib = "$App\bin\python\Lib"
$site = "$lib\site-packages"
$gone = "$site\pydeck\nbextension\static", "$site\pip", "$lib\ensurepip",
        "$lib\idlelib", "$lib\tkinter", "$site\pyarrow\include",
        "$App\bin\python\include", "$App\bin\python\tcl", "$App\bin\python\share"
$gone += (Get-ChildItem $site -Directory -Recurse |
    Where-Object Name -in "tests", "testing").FullName
$gone += (Get-ChildItem $site -Directory -Filter "pip-*.dist-info").FullName
Remove-Item ($gone | Where-Object { $_ }) -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "$site\pyarrow\arrow_flight.dll", "$site\pyarrow\_flight*.pyd" `
    -Force -ErrorAction SilentlyContinue
# Debug symbols, as the Mac build strips its own: 80-odd MB of the interpreter.
Get-ChildItem "$App\bin\python" -Recurse -Filter *.pdb | Remove-Item -Force
Write-Host "    $before -> $(Size $App)"

Step "[6/6] Launcher and packaging"
# pythonw, so no console window; start, so the double-click returns at once.
# %~dp0 keeps it all relative: the folder works wherever it is unzipped.
@'
@echo off
start "" "%~dp0bin\python\pythonw.exe" "%~dp0bootstrap.py"
'@ | Set-Content "$App\Plandrea.cmd" -Encoding ASCII

# A folder has no Info.plist to carry the version, so it says so in a file.
$Version | Set-Content "$App\VERSION" -Encoding ASCII
Write-Host "    $App ($(Size $App))"
if (-not $NoZip) {
    # No version in the name: that keeps the GitHub
    # releases/latest/download/<name> link permanent.
    $zip = "$Root\dist\Plandrea-windows-x64.zip"
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
    # bsdtar, shipped with Windows: far quicker than Compress-Archive here.
    tar -a -c -f $zip -C "$Root\dist" Plandrea
    Write-Host "    $zip ($('{0:N0} MB' -f ((Get-Item $zip).Length / 1MB)))"
}
Write-Host "`nDone."
