@echo off
rem One-click launcher: find pythonw.exe, then start the GUI.
rem Works no matter where Python is installed (no hardcoded path).
set "SCRIPT=%~dp0launcher.py"
set "PYW="

rem 1) pythonw.exe sitting next to this script
if exist "%~dp0pythonw.exe" set "PYW=%~dp0pythonw.exe"

rem 2) per-user install: %LOCALAPPDATA%\Programs\Python\Python3xx
for /d %%P in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%~P\pythonw.exe" if not defined PYW set "PYW=%%~P\pythonw.exe"

rem 3) root installs on any drive: C:\Python3xx, D:\Python3xx ...
for %%D in (C D E F) do for /d %%P in ("%%D:\Python3*") do if exist "%%~P\pythonw.exe" if not defined PYW set "PYW=%%~P\pythonw.exe"

rem 4) whatever is on PATH (skip the Microsoft Store stub)
for /f "delims=" %%P in ('where pythonw 2^>nul') do if not defined PYW echo %%P | findstr /i "WindowsApps" >nul || set "PYW=%%P"

if not defined PYW (
  echo.
  echo  [ERROR] pythonw.exe not found.
  echo  Please install Python 3 from https://www.python.org/downloads/
  echo  and tick "Add python.exe to PATH" while installing.
  echo.
  pause
  exit /b 1
)

start "" "%PYW%" "%SCRIPT%"
