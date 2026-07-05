$projectRoot = Join-Path $PSScriptRoot ".."

# Автообнаружение и активация venv
$venvPaths = @(
    "venv\Scripts\Activate.ps1",
    ".venv\Scripts\Activate.ps1",
    "env\Scripts\Activate.ps1"
)

$venvActivated = $false
Push-Location $projectRoot
foreach ($venvPath in $venvPaths) {
    if (Test-Path $venvPath) {
        Write-Host "Активация виртуального окружения: $venvPath"
        . $venvPath
        $venvActivated = $true
        break
    }
}
if (-not $venvActivated) {
    Write-Host "Виртуальное окружение не найдено. Попытка запустить без активации venv." -ForegroundColor Yellow
}

Write-Host "Запуск uvicorn сервера (http://127.0.0.1:8000)..."
uvicorn main:app --reload --host 127.0.0.1 --port 8000
Pop-Location
