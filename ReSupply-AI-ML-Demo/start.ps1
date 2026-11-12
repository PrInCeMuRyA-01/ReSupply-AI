param([switch]$MLDemo)
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot 'backend')
try {
    if (-not (Test-Path '.\.venv\Scripts\python.exe')) {
        Write-Host 'Creating the local Python environment...' -ForegroundColor Green
        $created = $false
        if (Get-Command py -ErrorAction SilentlyContinue) {
            $installed = (& py -0p 2>&1 | Out-String)
            $version = if ($installed -match '3\.12') { '-3.12' } elseif ($installed -match '3\.13') { '-3.13' } else { '-3' }
            & py $version -m venv .venv
            if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
            $created = $true
        }
        if (-not $created) {
            if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'Install Python 3.12 or 3.13, then run START-RESUPPLY.bat again.' }
            & python -m venv .venv
            if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment. Python 3.12 or 3.13 is recommended.' }
        }
    }
    $requirementsHash = (Get-FileHash '.\requirements.txt' -Algorithm SHA256).Hash
    $hashPath = '.\.venv\resupply-requirements.txt'
    $savedHash = if (Test-Path $hashPath) { (Get-Content $hashPath -Raw).Trim() } else { '' }
    if ($savedHash -ne $requirementsHash) {
        Write-Host 'Installing project packages. The first launch takes a few minutes...' -ForegroundColor Green
        & .\.venv\Scripts\python.exe -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) { throw 'Package installation failed. Check the internet connection and the error above.' }
        Set-Content -Path $hashPath -Value $requirementsHash
    }
    if (-not (Test-Path '.\.env')) { Copy-Item '.\.env.example' '.\.env' }
    if ($MLDemo) { & .\.venv\Scripts\python.exe run_easy.py --ml-demo }
    else { & .\.venv\Scripts\python.exe run_easy.py }
    if ($LASTEXITCODE -ne 0) { throw 'The server stopped with an error. See the message above.' }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
