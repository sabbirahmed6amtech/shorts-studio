@echo off
rem Start Shorts Studio on Windows. The first run sets everything up.
setlocal
cd /d "%~dp0"
title Shorts Studio

if exist ".venv\Scripts\python.exe" goto :deps

echo First run: setting up Shorts Studio. This takes a few minutes...
where uv >nul 2>nul
if errorlevel 1 goto :venv_python
uv venv --python 3.12 .venv
if errorlevel 1 goto :fail
goto :deps

:venv_python
set "PYCMD="
py -3.12 -c "import sys" >nul 2>nul && set "PYCMD=py -3.12"
if not defined PYCMD py -3.11 -c "import sys" >nul 2>nul && set "PYCMD=py -3.11"
if not defined PYCMD python -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>nul && set "PYCMD=python"
if not defined PYCMD goto :nopython
%PYCMD% -m venv .venv
if errorlevel 1 goto :fail

:deps
rem Install packages on the first run, and again whenever requirements.txt changes.
fc /b requirements.txt ".venv\.installed-requirements" >nul 2>nul
if not errorlevel 1 goto :run
echo Installing packages...
where uv >nul 2>nul
if errorlevel 1 goto :pip
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
if errorlevel 1 goto :fail
goto :stamp
:pip
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail
:stamp
copy /y requirements.txt ".venv\.installed-requirements" >nul

:run
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto :fail
goto :eof

:nopython
echo.
echo Python 3.11 or 3.12 is needed.
echo Install it from https://www.python.org/downloads/ and tick "Add Python to PATH",
echo or run:  winget install Python.Python.3.12
echo Then double-click start.bat again.
pause
exit /b 1

:fail
echo.
echo Something went wrong. Read the messages above.
pause
exit /b 1
