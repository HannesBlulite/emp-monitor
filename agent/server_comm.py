"""
Server Communication Module
Handles all HTTP communication between the agent and the Django server.
Includes screenshot upload, activity reporting, and settings retrieval.
"""

import json
import logging
import os
import time
from datetime import datetime

import requests

logger = logging.getLogger('emp_agent.server_comm')

# Timeout for HTTP requests (seconds)
REQUEST_TIMEOUT = 30


class ServerCommunicator:
    """
    Handles communication with the EMP Monitor server.
    Supports automatic retry and local queuing when server is unreachable.
    """

    def __init__(self, server_url, agent_token):
        self.server_url = server_url.rstrip('/')
        self.agent_token = agent_token
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Token {agent_token}',
            'User-Agent': 'EmpMonitorAgent/1.0',
        })
        self._queue_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'upload_queue'
        )
        os.makedirs(self._queue_dir, exist_ok=True)

    def upload_screenshot(self, monitor_index, image_bytes, width, height, timestamp):
        """
        Upload a screenshot to the server.

        Args:
            monitor_index: Which monitor (1, 2, 3...)
            image_bytes: Raw JPEG/PNG bytes
            width: Monitor width
            height: Monitor height
            timestamp: ISO format timestamp

        Returns:
            bool: True if upload succeeded, False otherwise
        """
        url = f'{self.server_url}/api/screenshots/upload/'

        try:
            files = {
                'image': (
                    f'screenshot_mon{monitor_index}_{timestamp.replace(":", "-")}.jpg',
                    image_bytes,
                    'image/jpeg'
                )
            }
            data = {
                'monitor_index': monitor_index,
                'width': width,
                'height': height,
                'timestamp': timestamp,
            }

            response = self.session.post(
                url, files=files, data=data, timeout=REQUEST_TIMEOUT
            )

            if response.status_code == 201:
                logger.info(f"Screenshot uploaded: monitor {monitor_index}")
                return True
            else:
                logger.warning(
                    f"Screenshot upload failed (HTTP {response.status_code}): "
                    f"{response.text[:200]}"
                )
                return False

        except requests.ConnectionError:
            logger.warning("Server unreachable — queuing screenshot locally")
            self._queue_screenshot(monitor_index, image_bytes, width, height, timestamp)
            return False
        except requests.Timeout:
            logger.warning("Upload timed out — queuing screenshot locally")
            self._queue_screenshot(monitor_index, image_bytes, width, height, timestamp)
            return False
        except Exception as e:
            logger.error(f"Screenshot upload error: {e}")
            return False

    def upload_activity_report(self, report):
        """
        Upload an activity report to the server.

        Args:
            report: Dict from ActivityTracker.get_report()

        Returns:
            bool: True if upload succeeded
        """
        url = f'{self.server_url}/api/activity/report/'

        try:
            response = self.session.post(
                url, json=report, timeout=REQUEST_TIMEOUT
            )

            if response.status_code == 201:
                logger.info("Activity report uploaded")
                return True
            else:
                logger.warning(
                    f"Activity report upload failed (HTTP {response.status_code}): "
                    f"{response.text[:200]}"
                )
                return False

        except requests.ConnectionError:
            logger.warning("Server unreachable — queuing activity report locally")
            self._queue_activity_report(report)
            return False
        except requests.Timeout:
            logger.warning("Activity report upload timed out")
            return False
        except Exception as e:
            logger.error(f"Activity report upload error: {e}")
            return False

    def get_settings(self):
        """
        Fetch agent settings from the server.

        Returns:
            dict or None: Settings dict, or None if server is unreachable
        """
        url = f'{self.server_url}/api/agent/settings/'

        try:
            response = self.session.get(url, timeout=REQUEST_TIMEOUT)

            if response.status_code == 200:
                settings = response.json()
                logger.info(f"Fetched settings from server: {settings}")
                return settings
            else:
                logger.warning(
                    f"Settings fetch failed (HTTP {response.status_code})"
                )
                return None

        except requests.ConnectionError:
            logger.warning("Server unreachable — using cached settings")
            return None
        except Exception as e:
            logger.error(f"Settings fetch error: {e}")
            return None

    def flush_queue(self):
        """
        Attempt to upload any queued screenshots/reports that were saved
        when the server was unreachable.
        """
        if not os.path.exists(self._queue_dir):
            return

        queued_files = sorted(os.listdir(self._queue_dir))
        if not queued_files:
            return

        logger.info(f"Flushing {len(queued_files)} queued item(s)")

        for filename in queued_files:
            filepath = os.path.join(self._queue_dir, filename)
            try:
                if filename.endswith('.json'):
                    # Activity report
                    with open(filepath, 'r') as f:
                        report = json.load(f)
                    if self.upload_activity_report(report):
                        os.remove(filepath)
                elif filename.endswith('.jpg') or filename.endswith('.png'):
                    # Screenshot — metadata is embedded in the filename
                    meta_path = filepath + '.meta'
                    if os.path.exists(meta_path):
                        with open(meta_path, 'r') as f:
                            meta = json.load(f)
                        with open(filepath, 'rb') as f:
                            image_bytes = f.read()
                        if self.upload_screenshot(
                            meta['monitor_index'], image_bytes,
                            meta['width'], meta['height'], meta['timestamp']
                        ):
                            os.remove(filepath)
                            os.remove(meta_path)
            except Exception as e:
                logger.error(f"Failed to flush queued item {filename}: {e}")

    def _queue_screenshot(self, monitor_index, image_bytes, width, height, timestamp):
        """Save a screenshot to the local queue for later upload."""
        safe_ts = timestamp.replace(':', '-').replace('T', '_')
        filename = f"screenshot_mon{monitor_index}_{safe_ts}.jpg"
        filepath = os.path.join(self._queue_dir, filename)
        meta_path = filepath + '.meta'

        try:
            with open(filepath, 'wb') as f:
                f.write(image_bytes)
            with open(meta_path, 'w') as f:
                json.dump({
                    'monitor_index': monitor_index,
                    'width': width,
                    'height': height,
                    'timestamp': timestamp,
                }, f)
            logger.debug(f"Queued screenshot: {filename}")
        except Exception as e:
            logger.error(f"Failed to queue screenshot: {e}")

    def _queue_activity_report(self, report):
        """Save an activity report to the local queue for later upload."""
        safe_ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"activity_{safe_ts}.json"
        filepath = os.path.join(self._queue_dir, filename)

        try:
            with open(filepath, 'w') as f:
                json.dump(report, f)
            logger.debug(f"Queued activity report: {filename}")
        except Exception as e:
            logger.error(f"Failed to queue activity report: {e}")

    # -------------------------------------------------------------------
    # Notification endpoints
    # -------------------------------------------------------------------

    def fetch_notifications(self):
        """
        Fetch pending (undelivered) notifications from the server.

        Returns:
            list of dict, each with 'id', 'type', 'title', 'message', 'created_at'
            or empty list on failure.
        """
        url = f'{self.server_url}/api/notifications/pending/'

        try:
            response = self.session.get(url, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                data = response.json()
                notifications = data.get('notifications', [])
                if notifications:
                    logger.info(f"Fetched {len(notifications)} pending notification(s)")
                return notifications
            else:
                logger.debug(f"Notifications fetch returned HTTP {response.status_code}")
                return []
        except requests.ConnectionError:
            logger.debug("Server unreachable — skipping notification check")
            return []
        except Exception as e:
            logger.debug(f"Notification fetch error: {e}")
            return []

    def ack_notification(self, notification_id):
        """
        Acknowledge a notification (mark as delivered on the server).

        Args:
            notification_id: The server-side notification PK

        Returns:
            bool: True if acknowledged successfully
        """
        url = f'{self.server_url}/api/notifications/{notification_id}/ack/'

        try:
            response = self.session.post(url, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                logger.info(f"Notification {notification_id} acknowledged")
                return True
            else:
                logger.warning(
                    f"Notification ack failed (HTTP {response.status_code})"
                )
                return False
        except Exception as e:
            logger.debug(f"Notification ack error: {e}")
            return False
