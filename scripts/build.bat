@echo off
REM Cree (si besoin) le venv Windows et installe/actualise open-loupedeck dedans.
setlocal
cd /d "%~dp0.."

set VENV_DIR=.venv
set PY=py -3.13

where py >nul 2>nul
if errorlevel 1 (
    set PY=python
) else (
    py -3.13 -c "" >nul 2>nul
    if errorlevel 1 set PY=py -3
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [1/3] Creation de l'environnement virtuel dans %VENV_DIR% ...
    %PY% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo Echec de la creation du venv. Verifiez qu'un Python 3.10+ est installe ^(py --list^).
        pause
        exit /b 1
    )
) else (
    echo [1/3] Environnement virtuel deja present, reutilisation.
)

echo [2/3] Mise a jour de pip ...
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo Echec de la mise a jour de pip.
    pause
    exit /b 1
)

echo [3/3] Installation de open-loupedeck (mode editable) ...
"%VENV_DIR%\Scripts\python.exe" -m pip install -e .
if errorlevel 1 (
    echo Echec de l'installation des dependances.
    pause
    exit /b 1
)

echo.
echo Build termine. Utilisez scripts\run.bat pour lancer l'agent.
pause
endlocal
