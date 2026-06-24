#!/bin/bash
# OmniMedia launcher for macOS.
# Move to the script's directory so paths resolve no matter how it's invoked.
cd "$(dirname "$0")" || exit 1

echo "==========================================="
echo "  OmniMedia Console - Launching on macOS"
echo "==========================================="

# Use the project's venv Python if present, else fall back to system python3.
PYBIN="python3"
if [ -x "venv/bin/python" ]; then
  PYBIN="$(pwd)/venv/bin/python"
fi

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null && [ ! -x "venv/bin/python" ]; then
    echo "Error: Python 3 is not installed or not in PATH."
    echo "Please install Python 3.x and make sure to add it to your PATH."
    echo "Press [Enter] to exit..."
    read
    exit 1
fi

# Create a virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment (venv)..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "Error: Failed to create virtual environment."
        echo "Press [Enter] to exit..."
        read
        exit 1
    fi
    PYBIN="$(pwd)/venv/bin/python"
fi

# Activate the virtual environment
source venv/bin/activate

# Install requirements only if dependencies are missing (keeps launches fast & offline-friendly).
if ! python -c "import webview, yt_dlp" 2>/dev/null; then
  echo "Checking and installing dependencies..."
  python -m pip install --upgrade pip --quiet
  python -m pip install -r requirements.txt --quiet
  if [ $? -ne 0 ]; then
      echo "Error: Dependency installation failed."
      echo "Press [Enter] to exit..."
      read
      exit 1
  fi
else
  echo "Dependencies already satisfied."
fi

# Check for yt-dlp and ffmpeg tools
echo "Checking system tools..."
if ! command -v yt-dlp &> /dev/null
then
    echo "Warning: 'yt-dlp' is not found in your PATH."
    echo "Make sure it is installed for the downloader to function correctly."
fi

if ! command -v ffmpeg &> /dev/null
then
    echo "Warning: 'ffmpeg' is not found in your PATH."
    echo "Make sure it is installed for the converter and trimmer to work."
fi

# Run the python script
echo "Launching desktop window..."
python app.py

# Deactivate virtual environment upon app close
deactivate
echo "App closed."
