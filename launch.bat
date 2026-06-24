@echo off
title OmniMedia Console Launcher
echo ===========================================
echo   OmniMedia Console - Launching on Windows
echo ===========================================

:: Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python is not installed or not in PATH.
    echo Please install Python 3.x and ensure you check "Add Python to PATH" during setup.
    pause
    exit /b 1
)

:: Create virtual environment if it doesn't exist
if not exist "venv" (
    echo Creating Python virtual environment (venv)...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo Error: Failed to create virtual environment.
        pause
        exit /b 1
    )
)

:: Activate virtual environment
call venv\Scripts\activate.bat

:: Install requirements
echo Checking and installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo Error: Dependency installation failed.
    pause
    exit /b 1
)

:: Check for tools (yt-dlp and ffmpeg)
where yt-dlp >nul 2>&1
if %errorlevel% neq 0 (
    echo Warning: 'yt-dlp' was not found in your PATH.
    echo Make sure it is installed for the downloader to function correctly.
)

where ffmpeg >nul 2>&1
if %errorlevel% neq 0 (
    echo Warning: 'ffmpeg' was not found in your PATH.
    echo Make sure it is installed for the converter and trimmer to work.
)

:: Launch application
echo Launching desktop window...
python app.py

:: Deactivate virtual environment
call venv\Scripts\deactivate.bat
echo App closed.
pause
