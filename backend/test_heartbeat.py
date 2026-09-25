"""
test_heartbeat.py — Test suite for browser heartbeat, multi-tab resilience, refresh safety,
and auto-shutdown triggering on tab closure.
"""

import asyncio
import time
import unittest
from fastapi.testclient import TestClient

from main import app
from services.heartbeat import HeartbeatManager

class TestHeartbeatManager(unittest.TestCase):
    def setUp(self):
        # Create a fresh isolated manager instance for each test
        self.manager = HeartbeatManager(
            startup_grace_seconds=1.0,
            heartbeat_timeout_seconds=3.0,
            grace_period_seconds=1.5
        )

    def test_01_single_tab_heartbeat_and_unload(self):
        tab_id = "test_tab_1"
        self.assertEqual(len(self.manager.active_tabs), 0)
        self.assertFalse(self.manager.has_received_heartbeat)

        # 1. Record heartbeat
        self.manager.record_heartbeat(tab_id)
        self.assertEqual(len(self.manager.active_tabs), 1)
        self.assertTrue(self.manager.has_received_heartbeat)
        self.assertIsNone(self.manager.last_empty_since)

        # 2. Record unload beacon
        self.manager.record_unload(tab_id)
        self.assertEqual(len(self.manager.active_tabs), 0)
        self.assertIsNotNone(self.manager.last_empty_since)

    def test_02_multi_tab_concurrency(self):
        tab_a = "tab_alpha"
        tab_b = "tab_beta"

        # Both tabs open
        self.manager.record_heartbeat(tab_a)
        self.manager.record_heartbeat(tab_b)
        self.assertEqual(len(self.manager.active_tabs), 2)
        self.assertIsNone(self.manager.last_empty_since)

        # Tab A closes; Tab B remains open
        self.manager.record_unload(tab_a)
        self.assertEqual(len(self.manager.active_tabs), 1)
        self.assertIn(tab_b, self.manager.active_tabs)
        # last_empty_since must remain None because Tab B is still active
        self.assertIsNone(self.manager.last_empty_since, "Shutdown timer must NOT start while Tab B is active")

        # Tab B sends regular heartbeat
        self.manager.record_heartbeat(tab_b)
        self.assertEqual(len(self.manager.active_tabs), 1)
        self.assertIsNone(self.manager.last_empty_since)

        # Tab B finally closes
        self.manager.record_unload(tab_b)
        self.assertEqual(len(self.manager.active_tabs), 0)
        self.assertIsNotNone(self.manager.last_empty_since, "Shutdown timer must start when all tabs are closed")

    def test_03_page_refresh_resilience(self):
        tab_id = "tab_refresh"

        # Tab active
        self.manager.record_heartbeat(tab_id)
        self.assertEqual(len(self.manager.active_tabs), 1)

        # User presses F5 / refreshes: unload fires
        self.manager.record_unload(tab_id)
        self.assertEqual(len(self.manager.active_tabs), 0)
        self.assertIsNotNone(self.manager.last_empty_since)

        # Immediately after (page reload completes in ~200ms), new heartbeat arrives
        time.sleep(0.2)
        self.manager.record_heartbeat(tab_id)

        # Assert tab is active again and shutdown timer is cleared
        self.assertEqual(len(self.manager.active_tabs), 1)
        self.assertIsNone(self.manager.last_empty_since, "Refresh must cancel the shutdown timer")
        self.assertFalse(self.manager.is_shutting_down)

    def test_04_watchdog_auto_shutdown_trigger(self):
        # Override trigger_shutdown to prevent terminating test runner
        shutdown_called = []
        self.manager.startup_grace_seconds = 0.5
        self.manager.grace_period_seconds = 0.8
        self.manager.check_interval_seconds = 0.2
        self.manager.trigger_shutdown = lambda: shutdown_called.append(True)

        async def run_scenario():
            # Start watchdog
            task = asyncio.create_task(self.manager.start_watchdog())

            # Simulate Tab active
            self.manager.record_heartbeat("tab_x")

            # Let startup grace elapse
            await asyncio.sleep(0.7)

            # Close tab
            self.manager.record_unload("tab_x")

            # Wait past grace_period_seconds (0.8s)
            await asyncio.sleep(1.2)

            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run_scenario())
        self.assertTrue(len(shutdown_called) > 0, "Watchdog must trigger shutdown after grace period expires")

    def test_05_http_heartbeat_endpoints(self):
        client = TestClient(app)

        # 1. Heartbeat POST
        res = client.post("/api/heartbeat", json={"tab_id": "client_tab_1"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"status": "ok"})

        # 2. Heartbeat status GET
        res_status = client.get("/api/heartbeat/status")
        self.assertEqual(res_status.status_code, 200)
        data = res_status.json()
        self.assertGreaterEqual(data["active_tab_count"], 1)
        self.assertIn("client_tab_1", data["active_tabs"])

        # 3. Unload beacon POST
        res_unload = client.post("/api/heartbeat/unload", json={"tab_id": "client_tab_1", "status": "closing"})
        self.assertEqual(res_unload.status_code, 200)
        self.assertEqual(res_unload.json(), {"status": "unloaded"})

if __name__ == "__main__":
    unittest.main()
