"""
EMP Monitor Agent — Main Entry Point

This is the main agent process. It can run in two modes:
  1. Console mode (for testing): python main.py
  2. Windows Service mode (for production): installed as a service

The agent periodically:
  - Captures screenshots from all monitors
  - Tracks user activity (active/idle time, foreground apps)
  - Uploads data to the server
  - Pulls updated settings from the server
"""

import json
import logging
import os
import sys
import threading
import time

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from screenshot import capture_all_monitors, save_screenshots_locally
from activity import ActivityTracker
from server_comm import ServerCommunicator
from notifier import show_toast
from updater import check_for_update, apply_update, restart_agent
from version import AGENT_VERSION

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')


def load_config():
    """Load agent configuration from config.json."""
    defaults = {
        'server_url': 'http://127.0.0.1:8000',
        'agent_token': '',
        'screenshot_interval_seconds': 300,
        'activity_report_interval_seconds': 60,
        'screenshot_quality': 60,
        'screenshot_format': 'JPEG',
        'idle_threshold_seconds': 120,
        'log_level': 'INFO',
    }

    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r') as f:
                loaded = json.load(f)
            defaults.update(loaded)
        except Exception as e:
            print(f"Warning: Could not load config.json: {e}")

    return defaults


def save_config(config):
    """Save configuration back to config.json."""
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=4)


# ---------------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------------

def setup_logging(log_level='INFO'):
    """Configure logging for the agent."""
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, 'agent.log')

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout),
        ]
    )


# ---------------------------------------------------------------------------
# Agent Core Loop
# ---------------------------------------------------------------------------

class EmpMonitorAgent:
    """Main agent class that coordinates screenshot capture and activity tracking."""

    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger('emp_agent')
        self.running = False

        # Initialize components
        self.communicator = ServerCommunicator(
            server_url=config['server_url'],
            agent_token=config['agent_token'],
        )
        self.activity_tracker = ActivityTracker(
            idle_threshold_seconds=config['idle_threshold_seconds']
        )

        # Timers
        self.screenshot_interval = config['screenshot_interval_seconds']
        self.activity_report_interval = config['activity_report_interval_seconds']
        self.activity_poll_interval = 5  # Poll activity every 5 seconds
        self.notification_poll_interval = 60  # Check for notifications every 60 seconds

    def start(self):
        """Start the agent."""
        self.running = True
        self.logger.info("=" * 60)
        self.logger.info("EMP Monitor Agent starting")
        self.logger.info(f"  Version: {AGENT_VERSION}")
        self.logger.info(f"  Server: {self.config['server_url']}")
        self.logger.info(f"  Screenshot interval: {self.screenshot_interval}s")
        self.logger.info(f"  Activity report interval: {self.activity_report_interval}s")
        self.logger.info("=" * 60)

        # Try to fetch latest settings from server
        self._refresh_settings()

        # Start worker threads
        threads = [
            threading.Thread(target=self._screenshot_loop, daemon=True, name='ScreenshotLoop'),
            threading.Thread(target=self._activity_poll_loop, daemon=True, name='ActivityPollLoop'),
            threading.Thread(target=self._activity_report_loop, daemon=True, name='ActivityReportLoop'),
            threading.Thread(target=self._queue_flush_loop, daemon=True, name='QueueFlushLoop'),
            threading.Thread(target=self._settings_refresh_loop, daemon=True, name='SettingsLoop'),
            threading.Thread(target=self._update_check_loop, daemon=True, name='UpdateLoop'),
            threading.Thread(target=self._notification_loop, daemon=True, name='NotificationLoop'),
        ]

        for t in threads:
            t.start()
            self.logger.info(f"Started thread: {t.name}")

        # Keep main thread alive
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("Ctrl+C received — shutting down")
            self.stop()

    def stop(self):
        """Stop the agent gracefully."""
        self.logger.info("Agent stopping...")
        self.running = False

        # Final activity report
        try:
            report = self.activity_tracker.get_report()
            if report['total_seconds'] > 0:
                self.communicator.upload_activity_report(report)
        except Exception as e:
            self.logger.error(f"Failed to send final activity report: {e}")

        self.logger.info("Agent stopped")

    # -----------------------------------------------------------------------
    # Worker Loops
    # -----------------------------------------------------------------------

    def _screenshot_loop(self):
        """Periodically capture and upload screenshots."""
        # Initial delay to let the system settle
        time.sleep(5)

        while self.running:
            try:
                self.logger.info("Capturing screenshots...")
                screenshots = capture_all_monitors(
                    quality=self.config.get('screenshot_quality', 60),
                    image_format=self.config.get('screenshot_format', 'JPEG'),
                )

                for shot in screenshots:
                    success = self.communicator.upload_screenshot(
                        monitor_index=shot['monitor_index'],
                        image_bytes=shot['image_bytes'],
                        width=shot['width'],
                        height=shot['height'],
                        timestamp=shot['timestamp'],
                    )
                    if not success:
                        # Already queued by communicator, just log
                        self.logger.debug(
                            f"Screenshot for monitor {shot['monitor_index']} "
                            f"queued for later upload"
                        )

            except Exception as e:
                self.logger.error(f"Screenshot loop error: {e}")

            # Wait for next interval
            self._interruptible_sleep(self.screenshot_interval)

    def _activity_poll_loop(self):
        """Poll activity state at short intervals to build accurate data."""
        while self.running:
            try:
                self.activity_tracker.poll()
            except Exception as e:
                self.logger.error(f"Activity poll error: {e}")
            self._interruptible_sleep(self.activity_poll_interval)

    def _activity_report_loop(self):
        """Periodically send activity reports to the server."""
        # Wait for some data to accumulate
        time.sleep(self.activity_report_interval)

        while self.running:
            try:
                report = self.activity_tracker.get_report()
                if report['total_seconds'] > 0:
                    self.communicator.upload_activity_report(report)
            except Exception as e:
                self.logger.error(f"Activity report loop error: {e}")

            self._interruptible_sleep(self.activity_report_interval)

    def _queue_flush_loop(self):
        """Periodically try to upload any queued items."""
        while self.running:
            try:
                self.communicator.flush_queue()
            except Exception as e:
                self.logger.error(f"Queue flush error: {e}")
            self._interruptible_sleep(120)  # Try every 2 minutes

    def _settings_refresh_loop(self):
        """Periodically fetch updated settings from the server."""
        while self.running:
            self._interruptible_sleep(300)  # Every 5 minutes
            self._refresh_settings()

    def _notification_loop(self):
        """Periodically check for and display pending notifications."""
        # Wait a bit after startup
        time.sleep(15)

        while self.running:
            try:
                notifications = self.communicator.fetch_notifications()
                for notif in notifications:
                    try:
                        show_toast(
                            title=notif.get('title', 'EMP Monitor'),
                            message=notif.get('message', ''),
                        )
                        # Acknowledge delivery
                        self.communicator.ack_notification(notif['id'])
                    except Exception as e:
                        self.logger.error(
                            f"Failed to show notification {notif.get('id')}: {e}"
                        )
            except Exception as e:
                self.logger.error(f"Notification loop error: {e}")

            self._interruptible_sleep(self.notification_poll_interval)

    def _update_check_loop(self):
        """Periodically check for agent updates."""
        # Wait 60 seconds after startup before first check
        self._interruptible_sleep(60)

        while self.running:
            try:
                result = check_for_update(
                    self.config['server_url'],
                    self.communicator.session,
                )
                if result and result.get('update_available'):
                    self.logger.info(
                        f"Update available: {AGENT_VERSION} -> "
                        f"{result['latest_version']}"
                    )
                    if apply_update(
                        self.config['server_url'],
                        self.communicator.session,
                        result['download_url'],
                    ):
                        self.logger.info("Update applied, restarting...")
                        self.stop()
                        restart_agent()
                        return
            except Exception as e:
                self.logger.error(f"Update check error: {e}")

            self._interruptible_sleep(3600)  # Check every hour

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _refresh_settings(self):
        """Fetch latest settings from server and apply them."""
        try:
            settings = self.communicator.get_settings()
            if settings:
                if 'screenshot_interval_seconds' in settings:
                    self.screenshot_interval = settings['screenshot_interval_seconds']
                if 'activity_report_interval_seconds' in settings:
                    self.activity_report_interval = settings['activity_report_interval_seconds']
                if 'idle_threshold_seconds' in settings:
                    self.activity_tracker.idle_threshold = settings['idle_threshold_seconds']
                if 'screenshot_quality' in settings:
                    self.config['screenshot_quality'] = settings['screenshot_quality']

                self.logger.info("Settings refreshed from server")
        except Exception as e:
            self.logger.warning(f"Could not refresh settings: {e}")

    def _interruptible_sleep(self, seconds):
        """Sleep in small increments so the agent can respond to stop quickly."""
        end_time = time.time() + seconds
        while self.running and time.time() < end_time:
            time.sleep(min(1.0, end_time - time.time()))


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def main():
    """Run the agent in console mode."""
    config = load_config()
    setup_logging(config.get('log_level', 'INFO'))

    agent = EmpMonitorAgent(config)
    agent.start()


if __name__ == '__main__':
    main()
