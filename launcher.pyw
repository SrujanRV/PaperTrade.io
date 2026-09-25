"""
launcher.pyw — Silent Windows launcher for PaperTrade.io.
Starts the unified backend (with embedded production frontend) if not already running,
and automatically opens the default web browser to http://localhost:8000.
"""

import os
import sys
import time
import urllib.request
import webbrowser
import subprocess

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
VENV_PYTHON = os.path.join(BACKEND_DIR, "venv", "Scripts", "python.exe")
HEALTH_URL = "http://127.0.0.1:8000/api/health"
APP_URL = "http://localhost:8000"

def is_server_running(timeout=1.0):
    try:
        req = urllib.request.Request(HEALTH_URL, headers={"User-Agent": "PaperTradeLauncher"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False

def launch(open_browser=True, exit_on_complete=False):
    # 1. Duplicate check: If already running, simply focus/open browser and exit
    if is_server_running():
        if open_browser:
            webbrowser.open(APP_URL)
        if exit_on_complete:
            sys.exit(0)
        return True

    # 2. Server not running — start it in the background silently
    python_bin = VENV_PYTHON if os.path.isfile(VENV_PYTHON) else sys.executable

    # Windows flags to ensure no console window appears, process is detached and breaks away from job
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    CREATE_NO_WINDOW = 0x08000000
    CREATE_BREAKAWAY_FROM_JOB = 0x01000000
    creationflags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW | CREATE_BREAKAWAY_FROM_JOB

    cmd = [python_bin, "-m", "uvicorn", "main:app", "--port", "8000"]
    log_path = os.path.join(BACKEND_DIR, "server.log")

    try:
        with open(log_path, "a", encoding="utf-8") as log_file:
            subprocess.Popen(
                cmd,
                cwd=BACKEND_DIR,
                creationflags=creationflags,
                close_fds=True,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=log_file
            )
    except Exception as e:
        err_log = os.path.join(PROJECT_ROOT, "launcher_error.log")
        with open(err_log, "w", encoding="utf-8") as f:
            f.write(f"Failed to start server: {e}\n")
        if exit_on_complete:
            sys.exit(1)
        return False

    # 3. Wait for the server to become responsive
    max_wait = 10.0
    start_time = time.time()
    while time.time() - start_time < max_wait:
        if is_server_running(timeout=0.4):
            break
        time.sleep(0.2)

    # 4. Open default web browser to the application
    if open_browser:
        webbrowser.open(APP_URL)

    if exit_on_complete:
        sys.exit(0)
    return True

if __name__ == "__main__":
    launch(open_browser=True, exit_on_complete=True)
