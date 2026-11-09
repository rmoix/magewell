@echo off
REM Construeix dist\MagewellNMS\MagewellNMS.exe en un PC Windows amb Python 3.10+.
setlocal
cd /d "%~dp0.."
set "PY=py -3"
where py >/dev/null 2>/dev/null || set "PY=python"
if not exist ".venv-build\Scripts\python.exe" %PY% -m venv .venv-build || ( pause & exit /b 1 )
".venv-build\Scripts\python.exe" -m pip install --upgrade pip
".venv-build\Scripts\python.exe" -m pip install -r requirements-dev.txt || ( pause & exit /b 1 )
".venv-build\Scripts\python.exe" -m pytest -q || ( echo Tests fallits & pause & exit /b 1 )
".venv-build\Scripts\python.exe" -m PyInstaller packaging\MagewellNMS.spec --noconfirm --clean || ( pause & exit /b 1 )
powershell -NoProfile -Command "Compress-Archive -Force -Path dist\MagewellNMS -DestinationPath dist\MagewellNMS-windows.zip"
echo.
echo Fet: dist\MagewellNMS\MagewellNMS.exe  i  dist\MagewellNMS-windows.zip
pause
