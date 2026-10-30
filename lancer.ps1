$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$labPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $labPython)) {
    Write-Host 'Preparation de Sentinel Lab pour cet ordinateur...'
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    $basePython = $null
    if ($pyLauncher) {
        try {
            $candidate = & $pyLauncher.Source -3.12 -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $candidate) { $basePython = [string]$candidate }
        } catch { }
    }
    if (-not $basePython -and $pythonCommand) { $basePython = $pythonCommand.Source }
    if (-not $basePython) { throw 'Installez Python 3.12 (64 bits), puis relancez DEMARRER.bat.' }
    $version = & $basePython -c "import sys; print('%d.%d' % sys.version_info[:2])"
    if ($LASTEXITCODE -ne 0 -or $version -ne '3.12') { throw 'Python 3.12 est requis pour ce paquet. Installez-le puis relancez.' }
    & $basePython -m venv (Join-Path $PSScriptRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Creation de l environnement Python impossible.' }
}
& $labPython -c "import importlib.util, sys; sys.exit(not all(importlib.util.find_spec(name) for name in ('fastapi', 'uvicorn', 'httpx', 'numpy', 'torch')))"
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Installation initiale ou reprise : Internet est necessaire. Patientez...'
    & $labPython -m pip install --disable-pip-version-check -r (Join-Path $PSScriptRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Installation incomplete. Verifiez Internet et relancez DEMARRER.bat.' }
}
try {
    $existing = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/state' -TimeoutSec 2
    if ($existing.target -eq 'http://127.0.0.1:8765/api/service') {
        Start-Process 'http://127.0.0.1:8765'
        Write-Host 'Le laboratoire fonctionne deja. Tableau de bord ouvert.'
        exit 0
    }
} catch { }
Write-Host 'SENTINEL LAB - API locale et autoencodeur PyTorch'
Write-Host 'Gardez cette fenetre ouverte pendant la demonstration. Ctrl+C pour quitter.'
& $labPython (Join-Path $PSScriptRoot 'run.py')
if ($LASTEXITCODE -ne 0) { throw 'Le laboratoire a rencontre une erreur. Conservez le message affiche.' }
