"""
services/heartbeat.py — Browser tab heartbeat and auto-shutdown watchdog for PaperTrade.
Tracks active browser tabs and triggers server shutdown when all tabs are closed
past a grace period (surviving refreshes, brief navigation, and multi-tab workflows).
"""

import asyncio
import logging
import os
import signal
import threading
import time
from typing import Optional, Dict

logger = logging.getLogger(__name__)

class HeartbeatManager:
    _instance: Optional["HeartbeatManager"] = None
    _server_instance = None  # Optional uvicorn.Server reference

    def __init__(
        self,
        startup_grace_seconds: float = 30.0,
        heartbeat_timeout_seconds: float = 15.0,
        grace_period_seconds: float = 15.0,
        check_interval_seconds: float = 1.0,
    ):
        self.startup_grace_seconds = startup_grace_seconds
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self.grace_period_seconds = grace_period_seconds
        self.check_interval_seconds = check_interval_seconds

        self.start_time = time.time()
        self.active_tabs: Dict[str, float] = {}  # tab_id -> last_heartbeat_timestamp
        self.has_received_heartbeat = False
        self.last_empty_since: Optional[float] = None
        self.is_shutting_down = False
        self._watchdog_task: Optional[asyncio.Task] = None
        self._lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "HeartbeatManager":
        if cls._instance is None:
            cls._instance = HeartbeatManager()
        return cls._instance

    @classmethod
    def set_server_instance(cls, server):
        cls._server_instance = server

    def record_heartbeat(self, tab_id: str):
        with self._lock:
            self.active_tabs[tab_id] = time.time()
            self.has_received_heartbeat = True
            self.last_empty_since = None

    def record_unload(self, tab_id: str):
        with self._lock:
            if tab_id in self.active_tabs:
                del self.active_tabs[tab_id]
            if len(self.active_tabs) == 0:
                self.last_empty_since = time.time()

    def get_status(self) -> dict:
        with self._lock:
            return {
                "active_tab_count": len(self.active_tabs),
                "active_tabs": list(self.active_tabs.keys()),
                "has_received_heartbeat": self.has_received_heartbeat,
                "uptime": time.time() - self.start_time,
                "last_empty_since": self.last_empty_since,
                "is_shutting_down": self.is_shutting_down,
            }

    def trigger_shutdown(self):
        if self.is_shutting_down:
            return
        self.is_shutting_down = True
        logger.info(
            "HeartbeatManager: All browser tabs closed past grace period (%ss). Initiating auto-shutdown...",
            self.grace_period_seconds,
        )

        # 1. If Uvicorn server reference is available, set should_exit
        if HeartbeatManager._server_instance is not None:
            try:
                HeartbeatManager._server_instance.should_exit = True
            except Exception as e:
                logger.warning("Failed setting server.should_exit: %s", e)

        # 2. Hard exit fallback after 2.0s to ensure guaranteed termination
        def hard_exit_fallback():
            time.sleep(2.0)
            logger.info("HeartbeatManager: Executing shutdown.")
            os._exit(0)

        t = threading.Thread(target=hard_exit_fallback, daemon=True)
        t.start()

        # 3. Signal main thread (SIGINT / CTRL_C_EVENT)
        try:
            os.kill(os.getpid(), signal.SIGINT)
        except Exception:
            pass

    async def start_watchdog(self):
        """Async loop evaluating tab heartbeat status every 2 seconds."""
        logger.info("HeartbeatManager: Watchdog started (startup_grace=%ss, tab_grace=%ss)",
                    self.startup_grace_seconds, self.grace_period_seconds)
        while not self.is_shutting_down:
            try:
                await asyncio.sleep(self.check_interval_seconds)
                now = time.time()

                with self._lock:
                    # If we haven't received any heartbeats yet, honor startup_grace_seconds
                    if not self.has_received_heartbeat:
                        if (now - self.start_time) < self.startup_grace_seconds:
                            continue
                        else:
                            logger.info("HeartbeatManager: Startup grace period elapsed without connection. Auto-shutting down.")
                            self.trigger_shutdown()
                            break

                    # Prune stale tabs that haven't sent a heartbeat within timeout
                    stale_tabs = [
                        tid for tid, last_seen in self.active_tabs.items()
                        if (now - last_seen) > self.heartbeat_timeout_seconds
                    ]
                    for tid in stale_tabs:
                        del self.active_tabs[tid]

                    # Check if empty
                    if len(self.active_tabs) == 0:
                        if self.has_received_heartbeat:
                            if self.last_empty_since is None:
                                self.last_empty_since = now
                            elif (now - self.last_empty_since) >= self.grace_period_seconds:
                                self.trigger_shutdown()
                                break
                    else:
                        self.last_empty_since = None

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in heartbeat watchdog: %s", e)
