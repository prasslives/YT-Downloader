#!/bin/bash
# Change directory to the folder where this script is located
cd "$(dirname "$0")"

echo "==========================================="
echo "  OmniMedia Console - Launching on macOS"
echo "==========================================="

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null
then
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
fi

# Activate the virtual environment
source venv/bin/activate

# Install requirements
echo "Checking and installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "Error: Dependency installation failed."
    echo "Press [Enter] to exit..."
    read
    exit 1
fi

# Run the python script
echo "Launching desktop window..."
python app.py

# Deactivate virtual environment upon app close
deactivate
echo "App closed."
