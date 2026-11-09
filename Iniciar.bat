@echo off
REM ==========================================================================
REM  Magewell Mini-NMS - arrencada des del codi font (cal Python 3.10+ i internet
REM  la primera vegada). Si tens el MagewellNMS.exe, no cal aquest fitxer.
REM ==========================================================================
setlocal
cd /d "%~dp0"

set "PY="
where py >/dev/null 2>/dev/null && set "PY=py -3"
if not defined PY ( where python >/dev/null 2>/dev/null && set "PY=python" )
if not defined PY (
  echo No sha trobat Python. Instal.lal des de https://www.python.org/downloads/
  echo i marca lopcio "Add python.exe to PATH".
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creant entorn virtual...
  %PY% -m venv .venv || ( pause & exit /b 1 )
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || ( pause & exit /b 1 )
)

".venv\Scripts\python.exe" -m app %*
if errorlevel 1 pause
