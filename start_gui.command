#!/bin/bash
# macOS: double-click to start (first time: in Terminal run  chmod +x start_gui.command ).
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 was not found. Install it from python.org (it includes Tk) and try again."
  read -n 1 -s -r -p "Press any key to close"
  exit 1
fi
python3 photo_tools_gui.py
