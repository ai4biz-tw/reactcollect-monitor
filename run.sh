#!/bin/bash
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "請先安裝 Python 3：https://www.python.org/downloads/"; exit 1; }
python3 app.py
