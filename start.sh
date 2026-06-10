#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "Installing Python dependencies..."
python3 -m pip install -q -r requirements.txt 2>/dev/null

echo "Installing Playwright browser..."
python3 -m playwright install chromium 2>/dev/null

echo ""
echo "Starting server at http://localhost:5000"
python3 app.py
