@echo off
REM Lance l'agent Loupedeck (interface web + device). Arguments supplementaires transmis tels quels,
REM ex: scripts\run.bat --no-device   ou   scripts\run.bat --config C:\chemin\config.yaml
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\open-loupedeck.exe" (
    echo Environnement non installe. Lancez d'abord scripts\build.bat
    pause
    exit /b 1
)

".venv\Scripts\open-loupedeck.exe" --web 127.0.0.1:8765 %*

endlocal
