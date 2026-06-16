@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  where py >nul 2>nul
  if errorlevel 1 (
    echo Python was not found. Please install Python 3.10+ and try again.
    pause
    exit /b 1
  )
  set "PY=py -3"
) else (
  set "PY=python"
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo Failed to create .venv.
    pause
    exit /b 1
  )
)

set "VENV_PY=.venv\Scripts\python.exe"
echo Installing requirements...
"%VENV_PY%" -m pip install --upgrade pip
if exist requirements.txt (
  "%VENV_PY%" -m pip install -r requirements.txt
) else (
  echo requirements.txt not found, continuing with standard library dependencies.
)
if errorlevel 1 (
  echo Dependency install failed.
  pause
  exit /b 1
)

echo Preparing local data directory...
"%VENV_PY%" scripts\bootstrap.py
if errorlevel 1 (
  echo Bootstrap failed.
  pause
  exit /b 1
)

echo Initializing database...
"%VENV_PY%" -c "import app; app.initialize(); print('database ready')"
if errorlevel 1 (
  echo Database initialization failed.
  pause
  exit /b 1
)

echo Starting Miaoshou workbench at http://127.0.0.1:8000
start "" http://127.0.0.1:8000
set "HOST=127.0.0.1"
set "PORT=8000"
"%VENV_PY%" app.py
pause
