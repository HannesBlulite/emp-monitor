"""
Agent Auto-Updater Module
Downloads new agent versions from the server and restarts the agent.
"""

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

import requests

from version import AGENT_VERSION

logger = logging.getLogger('emp_agent.updater')

# Files that get replaced during an update
UPDATABLE_FILES = [
    '__init__.py', 'main.py', 'activity.py', 'screenshot.py',
    'server_comm.py', 'service.py', 'version.py', 'updater.py',
    'requirements-agent.txt',
]

REQUEST_TIMEOUT = 60


def check_for_update(server_url, session):
    """
    Ask the server if a newer agent version is available.

    Returns:
        dict with 'update_available', 'latest_version', 'download_url'
        or None if check failed.
    """
    url = f'{server_url.rstrip("/")}/api/agent/update/check/'
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            data['update_available'] = data.get('latest_version', AGENT_VERSION) != AGENT_VERSION
            return data
        return None
    except Exception as e:
        logger.debug(f"Update check failed: {e}")
        return None


def apply_update(server_url, session, download_url):
    """
    Download the update ZIP and replace agent files.

    Returns True if the update was applied and a restart is needed.
    """
    agent_dir = os.path.dirname(os.path.abspath(__file__))
    tmp_dir = tempfile.mkdtemp(prefix='empagent_update_')
    zip_path = os.path.join(tmp_dir, 'update.zip')

    try:
        # Download the ZIP
        logger.info(f"Downloading update from {download_url}")
        full_url = f'{server_url.rstrip("/")}{download_url}'
        resp = session.get(full_url, timeout=120, stream=True)
        resp.raise_for_status()

        with open(zip_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        logger.info(f"Update downloaded ({os.path.getsize(zip_path)} bytes)")

        # Extract to temp dir
        extract_dir = os.path.join(tmp_dir, 'extracted')
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(extract_dir)

        # Copy updatable files over the current agent
        updated = []
        for filename in UPDATABLE_FILES:
            src = os.path.join(extract_dir, filename)
            if os.path.exists(src):
                dst = os.path.join(agent_dir, filename)
                shutil.copy2(src, dst)
                updated.append(filename)

        logger.info(f"Updated {len(updated)} files: {', '.join(updated)}")
        return True

    except Exception as e:
        logger.error(f"Update failed: {e}")
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def restart_agent():
    """Restart the agent process via Task Scheduler."""
    logger.info("Restarting agent via Task Scheduler...")
    try:
        # Stop then start the scheduled task — this kills the current process
        # and starts a fresh one
        subprocess.Popen(
            ['powershell', '-Command',
             'Stop-ScheduledTask -TaskName EmpMonitorAgent; '
             'Start-Sleep -Seconds 2; '
             'Start-ScheduledTask -TaskName EmpMonitorAgent'],
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        )
    except Exception as e:
        logger.error(f"Restart via Task Scheduler failed: {e}")
        # Fallback: just restart the Python process
        logger.info("Falling back to direct process restart")
        python = sys.executable
        os.execv(python, [python] + sys.argv)
