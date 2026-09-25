"""
test_windows_launcher.py — Verification for PaperTrade Windows Desktop Launcher,
browser selection, unified static frontend serving, and duplicate-instance detection.
"""

import os
import sys
import time
import unittest
import urllib.request
import json
import subprocess

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

import launcher

def _kill_port_8000():
    try:
        out = subprocess.check_output(["netstat", "-ano", "-p", "tcp"], text=True)
        for line in out.splitlines():
            if ":8000" in line and "LISTENING" in line:
                pid = line.strip().split()[-1]
                if pid.isdigit() and int(pid) > 0:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", pid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except Exception:
        pass

class TestWindowsLauncher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _kill_port_8000()
        time.sleep(1.0)

    @classmethod
    def tearDownClass(cls):
        _kill_port_8000()

    def test_01_launcher_cold_start_and_unified_serving(self):
        """Test that launcher starts the server and serves both static frontend and API on port 8000."""
        self.assertFalse(launcher.is_server_running(), "Server should not be running prior to launch")

        # Launch server (suppressing browser window popup during automated test)
        launcher.launch(open_browser_window=False, prompt_gui=False)
        self.assertTrue(launcher.is_server_running(), "Server must be running after launcher.launch()")

        # 1. Verify health check
        req = urllib.request.Request("http://127.0.0.1:8000/api/health")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data.get("status"), "ok")
            self.assertEqual(data.get("version"), "0.2.0")

        # 2. Verify root serves the production frontend index.html
        req_root = urllib.request.Request("http://127.0.0.1:8000/")
        with urllib.request.urlopen(req_root, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            content = resp.read().decode("utf-8")
            self.assertIn("PaperTrade", content, "Root page must contain PaperTrade title/content")
            self.assertIn("/assets/", content, "Root page must reference static assets")

        # 3. Verify SPA fallback works for arbitrary client routes
        req_spa = urllib.request.Request("http://127.0.0.1:8000/portfolio")
        with urllib.request.urlopen(req_spa, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            content = resp.read().decode("utf-8")
            self.assertIn("PaperTrade", content, "SPA fallback route must serve index.html")

        # 4. Verify API 404 is NOT hijacked by SPA fallback
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen("http://127.0.0.1:8000/api/nonexistent_endpoint", timeout=3.0)
        self.assertEqual(ctx.exception.code, 404)

    def test_02_duplicate_instance_detection(self):
        """Test that running launcher when server is already running detects it and avoids duplicates."""
        self.assertTrue(launcher.is_server_running(), "Server should already be running")

        out_before = subprocess.check_output(["netstat", "-ano", "-p", "tcp"], text=True)
        listening_before = [line for line in out_before.splitlines() if ":8000" in line and "LISTENING" in line]
        self.assertGreaterEqual(len(listening_before), 1, "Should have 1 listening server process on port 8000")

        # Launch again with duplicate check
        launcher.launch(open_browser_window=False, prompt_gui=False)

        time.sleep(0.5)
        out_after = subprocess.check_output(["netstat", "-ano", "-p", "tcp"], text=True)
        listening_after = [line for line in out_after.splitlines() if ":8000" in line and "LISTENING" in line]

        self.assertEqual(len(listening_before), len(listening_after), "Duplicate server must NOT be spawned")
        self.assertTrue(launcher.is_server_running(), "Server must remain healthy and responsive")

    def test_03_browser_resolution_and_persistence(self):
        """Test that browser resolution handles detected browsers and persists user config."""
        browsers = launcher.detect_installed_browsers()
        self.assertGreaterEqual(len(browsers), 1)

        # Set a test preference
        first_name, first_path = next(iter(browsers.items()))
        launcher.save_browser_pref(first_name, first_path)

        resolved_path = launcher.resolve_browser(force_prompt=False)
        self.assertEqual(resolved_path, first_path)

    def test_04_desktop_shortcuts_integrity(self):
        """Verify that only PaperTrade.io.lnk exists on Desktop and Stop PaperTrade.lnk is removed."""
        desktop = os.path.expanduser("~/Desktop")
        app_lnk = os.path.join(desktop, "PaperTrade.io.lnk")
        stop_lnk = os.path.join(desktop, "Stop PaperTrade.lnk")

        self.assertTrue(os.path.isfile(app_lnk), "PaperTrade.io.lnk must exist on Desktop")
        self.assertFalse(os.path.isfile(stop_lnk), "Stop PaperTrade.lnk must NOT exist on Desktop")

if __name__ == "__main__":
    unittest.main()
