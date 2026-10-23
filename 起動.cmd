@echo off
if exist "%LOCALAPPDATA%\CodexUsage\bin\CodexUsage.exe" (
    start "" "%LOCALAPPDATA%\CodexUsage\bin\CodexUsage.exe"
) else if exist "%~dp0dist\CodexUsage.exe" (
    start "" "%~dp0dist\CodexUsage.exe"
) else (
    start "" "C:\Python312\pythonw.exe" "%~dp0app.py"
)
