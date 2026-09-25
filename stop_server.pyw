"""
stop_server.pyw — Stops the PaperTrade server running on port 8000.
"""

import os
import sys
import subprocess

def stop():
    try:
        output = subprocess.check_output(
            ["netstat", "-ano", "-p", "tcp"],
            creationflags=0x08000000,  # CREATE_NO_WINDOW
            text=True
        )
    except Exception:
        return

    pids_to_kill = set()
    for line in output.splitlines():
        if ":8000" in line and "LISTENING" in line:
            parts = line.strip().split()
            if len(parts) >= 5:
                pid = parts[-1]
                if pid.isdigit() and int(pid) > 0:
                    pids_to_kill.add(pid)

    for pid in pids_to_kill:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", pid],
                creationflags=0x08000000,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False
            )
        except Exception:
            pass

if __name__ == "__main__":
    stop()
