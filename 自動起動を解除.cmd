@echo off
if exist "%LOCALAPPDATA%\CodexUsage\bin\CodexUsage.exe" (
    "%LOCALAPPDATA%\CodexUsage\bin\CodexUsage.exe" --disable-startup
) else (
    python "%~dp0app.py" --disable-startup
)
