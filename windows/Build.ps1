param(
    [string]$Python = ""
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

if ([string]::IsNullOrWhiteSpace($Python)) {
    $workspacePython = Join-Path $PSScriptRoot '..\..\.venv\Scripts\python.exe'
    $localPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $workspacePython) {
        $Python = (Resolve-Path -LiteralPath $workspacePython).Path
    } elseif (Test-Path -LiteralPath $localPython) {
        $Python = (Resolve-Path -LiteralPath $localPython).Path
    } else {
        throw 'Python environment not found. Run Setup.ps1 or pass -Python C:\path\to\python.exe.'
    }
} elseif (-not (Test-Path -LiteralPath $Python)) {
    throw "Python executable not found: $Python"
} else {
    $Python = (Resolve-Path -LiteralPath $Python).Path
}

& $Python -m pip install --disable-pip-version-check -r requirements.txt 'pyinstaller==6.22.2'
if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed.' }

& $Python package_release.py prepare-notices
if ($LASTEXITCODE -ne 0) { throw 'Third-party notice preparation failed.' }

& $Python -m PyInstaller --clean --noconfirm KeydousCodex.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }

& $Python package_release.py release
if ($LASTEXITCODE -ne 0) { throw 'Release packaging failed.' }

Write-Host ''
Write-Host 'Built applications:'
Write-Host '  dist\KeydousCodex\KeydousCodex.exe'
Write-Host '  dist\KeydousCodex\KeydousCodexHook.exe'
Write-Host 'Release archives:'
Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'release') -Filter 'KeydousCodex-0.3.0-*.zip' |
    Sort-Object Name |
    ForEach-Object { Write-Host "  release\$($_.Name)" }
