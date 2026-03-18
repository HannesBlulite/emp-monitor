"""
Activity Tracker Module
Tracks user activity: idle time, active time, foreground application, and window titles.
Uses Windows API via ctypes.
"""

import ctypes
import ctypes.wintypes
import logging
import time
from datetime import datetime, timedelta
from collections import defaultdict

try:
    from browser_url import (
        is_browser_process, get_browser_url, extract_domain,
        extract_domain_from_title,
    )
    HAS_BROWSER_URL = True
except ImportError:
    HAS_BROWSER_URL = False

logger = logging.getLogger('emp_agent.activity')

# Windows API structures and functions
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize', ctypes.c_uint),
        ('dwTime', ctypes.c_uint),
    ]


def get_idle_duration_seconds():
    """
    Get the number of seconds since the last user input (mouse/keyboard).
    Uses Windows GetLastInputInfo API.
    """
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if user32.GetLastInputInfo(ctypes.byref(lii)):
        millis_since_input = kernel32.GetTickCount() - lii.dwTime
        return millis_since_input / 1000.0
    return 0.0


def get_foreground_window_info():
    """
    Get information about the currently active (foreground) window.

    Returns:
        dict: {
            'window_title': str,
            'process_name': str,
            'process_id': int
        }
    """
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return {'window_title': '', 'process_name': '', 'process_id': 0, 'hwnd': 0}

        # Get window title
        length = user32.GetWindowTextLengthW(hwnd)
        title_buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, length + 1)
        window_title = title_buffer.value

        # Get process ID
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process_id = pid.value

        # Get process name from PID
        process_name = _get_process_name(process_id)

        return {
            'window_title': window_title,
            'process_name': process_name,
            'process_id': process_id,
            'hwnd': hwnd,
        }
    except Exception as e:
        logger.error(f"Failed to get foreground window info: {e}")
        return {'window_title': '', 'process_name': '', 'process_id': 0, 'hwnd': 0}


def _get_process_name(pid):
    """Get the executable name for a given process ID."""
    try:
        # Open process with limited query rights
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return 'unknown'

        # Get process image file name
        buffer = ctypes.create_unicode_buffer(512)
        size = ctypes.wintypes.DWORD(512)

        # Use QueryFullProcessImageNameW
        try:
            result = kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size)
            )
            if result:
                # Extract just the filename from the full path
                full_path = buffer.value
                return full_path.rsplit('\\', 1)[-1] if '\\' in full_path else full_path
        finally:
            kernel32.CloseHandle(handle)

    except Exception as e:
        logger.debug(f"Could not get process name for PID {pid}: {e}")

    return 'unknown'


class ActivityTracker:
    """
    Tracks user activity over time. Call `poll()` at regular intervals
    (e.g. every 5-10 seconds) to build up activity data.
    """

    def __init__(self, idle_threshold_seconds=120):
        self.idle_threshold = idle_threshold_seconds
        self.active_seconds = 0.0
        self.idle_seconds = 0.0
        self.last_poll_time = None
        self.app_usage = defaultdict(float)  # process_name -> seconds
        self.domain_usage = defaultdict(float)  # domain -> seconds
        self.window_log = []  # list of (timestamp, window_title, process_name)
        self._last_window_info = None
        self._last_window_start = None

    def poll(self):
        """
        Called at regular intervals to sample activity state.
        Returns the current status: 'active' or 'idle'.
        """
        now = datetime.now()
        idle_secs = get_idle_duration_seconds()
        is_active = idle_secs < self.idle_threshold

        if self.last_poll_time is not None:
            elapsed = (now - self.last_poll_time).total_seconds()
            # Cap elapsed to avoid huge jumps (e.g. if machine was asleep)
            elapsed = min(elapsed, 60.0)

            if is_active:
                self.active_seconds += elapsed
            else:
                self.idle_seconds += elapsed

            # Track foreground app usage
            if is_active:
                window_info = get_foreground_window_info()
                process_name = window_info.get('process_name', 'unknown')
                self.app_usage[process_name] += elapsed

                # Extract domain if this is a browser
                domain = ''
                if HAS_BROWSER_URL and is_browser_process(process_name):
                    hwnd = window_info.get('hwnd', 0)
                    if hwnd:
                        url = get_browser_url(hwnd)
                        if url:
                            domain = extract_domain(url)
                    # Fallback: try to extract from window title
                    if not domain:
                        domain = extract_domain_from_title(
                            window_info.get('window_title', ''),
                            process_name,
                        )
                    if domain:
                        self.domain_usage[domain] += elapsed

                # Log window changes
                if (self._last_window_info is None or
                        window_info['window_title'] != self._last_window_info.get('window_title')):
                    # Save the previous window's duration
                    if self._last_window_info and self._last_window_start:
                        duration = (now - self._last_window_start).total_seconds()
                        prev_domain = self._last_window_info.get('domain', '')
                        self.window_log.append({
                            'timestamp': self._last_window_start.isoformat(),
                            'window_title': self._last_window_info['window_title'],
                            'process_name': self._last_window_info['process_name'],
                            'duration_seconds': round(duration, 1),
                            'domain': prev_domain,
                        })

                    window_info['domain'] = domain
                    self._last_window_info = window_info
                    self._last_window_start = now

        self.last_poll_time = now
        return 'active' if is_active else 'idle'

    def get_report(self):
        """
        Get a summary report of tracked activity. Resets counters after reporting.

        Returns:
            dict: {
                'timestamp': str,
                'active_seconds': float,
                'idle_seconds': float,
                'total_seconds': float,
                'productivity_ratio': float,  # 0.0 to 1.0
                'app_usage': {'chrome.exe': 120.5, 'code.exe': 300.0, ...},
                'window_log': [...]
            }
        """
        total = self.active_seconds + self.idle_seconds
        ratio = self.active_seconds / total if total > 0 else 0.0

        # Finalize the current window entry
        if self._last_window_info and self._last_window_start:
            duration = (datetime.now() - self._last_window_start).total_seconds()
            self.window_log.append({
                'timestamp': self._last_window_start.isoformat(),
                'window_title': self._last_window_info['window_title'],
                'process_name': self._last_window_info['process_name'],
                'duration_seconds': round(duration, 1),
                'domain': self._last_window_info.get('domain', ''),
            })

        report = {
            'timestamp': datetime.now().isoformat(),
            'active_seconds': round(self.active_seconds, 1),
            'idle_seconds': round(self.idle_seconds, 1),
            'total_seconds': round(total, 1),
            'productivity_ratio': round(ratio, 3),
            'app_usage': dict(self.app_usage),
            'domain_usage': dict(self.domain_usage),
            'window_log': list(self.window_log),
        }

        # Reset counters
        self.active_seconds = 0.0
        self.idle_seconds = 0.0
        self.app_usage = defaultdict(float)
        self.domain_usage = defaultdict(float)
        self.window_log = []
        self._last_window_info = None
        self._last_window_start = None

        return report


if __name__ == '__main__':
    # Quick test: poll activity every 2 seconds for 20 seconds
    logging.basicConfig(level=logging.DEBUG)
    tracker = ActivityTracker(idle_threshold_seconds=10)

    print("Tracking activity for 20 seconds... move your mouse and switch windows!")
    for i in range(10):
        status = tracker.poll()
        idle = get_idle_duration_seconds()
        window = get_foreground_window_info()
        print(f"  [{i+1}] Status: {status} | Idle: {idle:.1f}s | "
              f"App: {window['process_name']} | Title: {window['window_title'][:60]}")
        time.sleep(2)

    report = tracker.get_report()
    print(f"\n--- Activity Report ---")
    print(f"Active: {report['active_seconds']}s")
    print(f"Idle: {report['idle_seconds']}s")
    print(f"Productivity ratio: {report['productivity_ratio']:.0%}")
    print(f"App usage:")
    for app, secs in sorted(report['app_usage'].items(), key=lambda x: -x[1]):
        print(f"  {app}: {secs:.1f}s")
