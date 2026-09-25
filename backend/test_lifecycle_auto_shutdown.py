"""
test_lifecycle_auto_shutdown.py — End-to-end live lifecycle test:
- Tab connect & periodic heartbeats keep server alive
- Page refresh (unload + reconnect) does NOT shut down the server
- Multi-tab (close 1 tab while another remains open) does NOT shut down the server
- Closing the final tab triggers automatic server shutdown after grace period
"""

import json
import os
import subprocess
import sys
import time
import unittest
import urllib.request

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

import launcher

def is_port_8000_listening():
    try:
        out = subprocess.check_output(["netstat", "-ano", "-p", "tcp"], text=True)
        return any(":8000" in line and "LISTENING" in line for line in out.splitlines())
    except Exception:
        return False

def post_json(url, data):
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=3.0) as resp:
        return json.loads(resp.read().decode("utf-8"))

def get_json(url):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=3.0) as resp:
        return json.loads(resp.read().decode("utf-8"))

class TestLifecycleAutoShutdown(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Clean start
        if is_port_8000_listening():
            try:
                out = subprocess.check_output(["netstat", "-ano", "-p", "tcp"], text=True)
                for line in out.splitlines():
                    if ":8000" in line and "LISTENING" in line:
                        pid = line.strip().split()[-1]
                        subprocess.run(["taskkill", "/F", "/T", "/PID", pid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            except Exception:
                pass
            time.sleep(1.0)

        # Launch server
        launcher.launch(open_browser_window=False, prompt_gui=False)
        time.sleep(1.0)

    def test_full_lifecycle(self):
        self.assertTrue(is_port_8000_listening(), "Server must be running on port 8000")

        # 1. Tab 1 connects
        tab1 = "lifecycle_tab_1"
        res = post_json("http://127.0.0.1:8000/api/heartbeat", {"tab_id": tab1})
        self.assertEqual(res.get("status"), "ok")

        status = get_json("http://127.0.0.1:8000/api/heartbeat/status")
        self.assertEqual(status["active_tab_count"], 1)
        self.assertIn(tab1, status["active_tabs"])

        # 2. Tab 2 connects (multi-tab scenario)
        tab2 = "lifecycle_tab_2"
        post_json("http://127.0.0.1:8000/api/heartbeat", {"tab_id": tab2})
        status = get_json("http://127.0.0.1:8000/api/heartbeat/status")
        self.assertEqual(status["active_tab_count"], 2)

        # 3. Tab 1 closes -> Tab 2 is still open -> Server must remain running!
        post_json("http://127.0.0.1:8000/api/heartbeat/unload", {"tab_id": tab1, "status": "closing"})
        status = get_json("http://127.0.0.1:8000/api/heartbeat/status")
        self.assertEqual(status["active_tab_count"], 1)
        self.assertIn(tab2, status["active_tabs"])
        self.assertIsNone(status["last_empty_since"], "Shutdown timer must NOT start while Tab 2 is active")
        self.assertTrue(is_port_8000_listening(), "Server must remain running while Tab 2 is open")

        # 4. Tab 2 simulates refresh (F5: unload beacon followed immediately by heartbeat)
        post_json("http://127.0.0.1:8000/api/heartbeat/unload", {"tab_id": tab2, "status": "closing"})
        time.sleep(0.3)
        post_json("http://127.0.0.1:8000/api/heartbeat", {"tab_id": tab2})
        status = get_json("http://127.0.0.1:8000/api/heartbeat/status")
        self.assertEqual(status["active_tab_count"], 1, "Tab 2 reconnected after reload")
        self.assertIsNone(status["last_empty_since"], "Shutdown timer must be cleared by reload heartbeat")
        self.assertTrue(is_port_8000_listening(), "Server must NOT shut down on refresh")

        # 5. Tab 2 closes for real (user closes final browser window)
        post_json("http://127.0.0.1:8000/api/heartbeat/unload", {"tab_id": tab2, "status": "closing"})
        status = get_json("http://127.0.0.1:8000/api/heartbeat/status")
        self.assertEqual(status["active_tab_count"], 0)
        self.assertIsNotNone(status["last_empty_since"], "Shutdown timer must start now that 0 tabs remain")

        # 6. Wait for grace period (15s grace + watchdog check ~ 18s total)
        print("\nWaiting for 15s grace period auto-shutdown...")
        start_wait = time.time()
        server_stopped = False
        while time.time() - start_wait < 25.0:
            if not is_port_8000_listening():
                server_stopped = True
                break
            time.sleep(1.0)

        elapsed = time.time() - start_wait
        self.assertTrue(server_stopped, f"Server must automatically shut down after grace period! (waited {elapsed:.1f}s)")
        print(f"PASS: Server cleanly auto-terminated after {elapsed:.1f}s of silence!")

if __name__ == "__main__":
    unittest.main()
