"""
run_server.py — Dedicated silent runner for Uvicorn under pythonw.exe.
Sets up standard streams before uvicorn or logging can initialize,
guaranteeing zero command prompt / console windows on Windows.
"""

import os
import sys

# Ensure stdout and stderr are valid streams so pythonw.exe doesn't crash logging/uvicorn
current_dir = os.path.dirname(os.path.abspath(__file__))
log_path = os.path.join(current_dir, "server.log")

try:
    _log_stream = open(log_path, "a", encoding="utf-8", buffering=1)
except Exception:
    _log_stream = open(os.devnull, "w", encoding="utf-8")

if sys.stdout is None:
    sys.stdout = _log_stream
if sys.stderr is None:
    sys.stderr = _log_stream

import uvicorn
from main import app

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, log_level="info", reload=True)
