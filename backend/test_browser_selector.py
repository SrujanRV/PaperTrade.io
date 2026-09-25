"""
test_browser_selector.py — Unit test suite for Windows browser detection and configuration persistence.
"""

import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

import launcher

class TestBrowserSelector(unittest.TestCase):
    def setUp(self):
        self.backup_config = None
        if os.path.isfile(launcher.CONFIG_PATH):
            with open(launcher.CONFIG_PATH, "r", encoding="utf-8") as f:
                self.backup_config = f.read()
            os.remove(launcher.CONFIG_PATH)

    def tearDown(self):
        if self.backup_config is not None:
            with open(launcher.CONFIG_PATH, "w", encoding="utf-8") as f:
                f.write(self.backup_config)
        elif os.path.isfile(launcher.CONFIG_PATH):
            os.remove(launcher.CONFIG_PATH)

    def test_01_detect_installed_browsers(self):
        browsers = launcher.detect_installed_browsers()
        self.assertIsInstance(browsers, dict)
        self.assertGreaterEqual(len(browsers), 1, "At least one browser must be installed")
        # Chrome or Edge should be detected on this Windows environment
        self.assertTrue(
            "Microsoft Edge" in browsers or "Google Chrome" in browsers,
            f"Expected Edge or Chrome in detected browsers: {list(browsers.keys())}"
        )
        for name, path in browsers.items():
            self.assertTrue(os.path.isfile(path), f"Browser executable path for {name} does not exist: {path}")

    def test_02_config_persistence(self):
        name_before, path_before = launcher.get_saved_browser_pref()
        self.assertIsNone(name_before)
        self.assertIsNone(path_before)

        # Save preference
        test_name = "Microsoft Edge"
        test_path = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"
        launcher.save_browser_pref(test_name, test_path)

        # Read back
        saved_name, saved_path = launcher.get_saved_browser_pref()
        self.assertEqual(saved_name, test_name)
        self.assertEqual(saved_path, test_path)

if __name__ == "__main__":
    unittest.main()
