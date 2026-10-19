@echo off
setlocal
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"
if exist "%PY%" goto RUN

echo [tw.bat] .venv not found, using system python.
echo [tw.bat] If you see ModuleNotFoundError, run:
echo [tw.bat]     python -m venv .venv
echo [tw.bat]     .venv\Scripts\python.exe -m pip install -r requirements.txt
echo.
set "PY=python"

:RUN
"%PY%" tw.py %*
echo.
echo [tw.bat] exit code: %ERRORLEVEL%
pause
endlocal
