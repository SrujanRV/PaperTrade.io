"""
test_windows_launcher.py — Comprehensive verification for PaperTrade Windows Desktop Launcher,
unified production frontend serving, duplicate-instance detection, and stop_server utility.
"""

import os
import sys
import time
import unittest
import urllib.request
import json
import subprocess

# Ensure import paths
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

import launcher
import stop_server

class TestWindowsLauncher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure clean state: stop any existing server
        stop_server.stop()
        time.sleep(1.0)

    @classmethod
    def tearDownClass(cls):
        # Clean up after all tests
        stop_server.stop()

    def test_01_launcher_cold_start_and_unified_serving(self):
        """Test that launcher starts the server and serves both static frontend and API on port 8000."""
        self.assertFalse(launcher.is_server_running(), "Server should not be running prior to launch")

        # Launch server
        launcher.launch()
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

        # Record count of listening ports/processes
        out_before = subprocess.check_output(["netstat", "-ano", "-p", "tcp"], text=True)
        listening_before = [line for line in out_before.splitlines() if ":8000" in line and "LISTENING" in line]
        self.assertGreaterEqual(len(listening_before), 1, "Should have 1 listening server process on port 8000")

        # Launch again
        launcher.launch()

        # Check listening ports/processes again
        time.sleep(0.5)
        out_after = subprocess.check_output(["netstat", "-ano", "-p", "tcp"], text=True)
        listening_after = [line for line in out_after.splitlines() if ":8000" in line and "LISTENING" in line]

        # There should not be multiple conflicting servers
        self.assertEqual(len(listening_before), len(listening_after), "Duplicate server must NOT be spawned")
        self.assertTrue(launcher.is_server_running(), "Server must remain healthy and responsive")

    def test_03_stop_server_utility(self):
        """Test that stop_server.pyw cleanly terminates the server running on port 8000."""
        self.assertTrue(launcher.is_server_running(), "Server should be running before stop")

        stop_server.stop()
        time.sleep(1.5)

        self.assertFalse(launcher.is_server_running(), "Server must NOT be running after stop_server.stop()")

        out = subprocess.check_output(["netstat", "-ano", "-p", "tcp"], text=True)
        listening = [line for line in out.splitlines() if ":8000" in line and "LISTENING" in line]
        self.assertEqual(len(listening), 0, "No process should be LISTENING on port 8000")

    def test_04_relaunch_after_stop(self):
        """Test that launcher can cleanly re-launch the server after being stopped."""
        self.assertFalse(launcher.is_server_running(), "Server should not be running")

        launcher.launch()
        self.assertTrue(launcher.is_server_running(), "Server must be running after re-launch")

        # Clean up
        stop_server.stop()
        time.sleep(1.0)
        self.assertFalse(launcher.is_server_running(), "Server stopped after test")

if __name__ == "__main__":
    unittest.main()
