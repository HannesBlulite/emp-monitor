"""
Agent Notifier Module — Windows Toast Notifications

Displays Windows 10/11 toast notifications to the employee.
Uses only ctypes and subprocess — no third-party dependencies.
Falls back to a simple MessageBox if toast is unavailable.
"""

import logging
import subprocess
import sys

logger = logging.getLogger('emp_agent.notifier')


def show_toast(title, message, app_name='EMP Monitor'):
    """
    Show a Windows toast notification.

    Uses PowerShell's BurntToast-style inline script for modern toast,
    falling back to a balloon tip notification via PowerShell.

    Args:
        title: Notification title (short)
        message: Notification body text
        app_name: App identifier shown in the notification
    """
    try:
        _show_toast_powershell(title, message, app_name)
    except Exception as e:
        logger.warning(f"Toast notification failed: {e}")
        try:
            _show_balloon_tip(title, message, app_name)
        except Exception as e2:
            logger.error(f"Balloon tip also failed: {e2}")


def _show_toast_powershell(title, message, app_name):
    """
    Show a toast using PowerShell and the Windows.UI.Notifications API.
    Works on Windows 10+ without any extra modules.
    """
    # Escape single quotes for PowerShell
    safe_title = title.replace("'", "''").replace("\n", " ")
    safe_message = message.replace("'", "''").replace("\n", "&#xA;")

    ps_script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime] | Out-Null

$template = @"
<toast>
    <visual>
        <binding template="ToastGeneric">
            <text>{safe_title}</text>
            <text>{safe_message}</text>
        </binding>
    </visual>
</toast>
"@

$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)

$appId = '{{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}}\\WindowsPowerShell\\v1.0\\powershell.exe'
$toast = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId)
$toast.Show([Windows.UI.Notifications.ToastNotification]::new($xml))
"""

    result = subprocess.run(
        ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_script],
        capture_output=True,
        timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
    )

    if result.returncode != 0:
        stderr = result.stderr.decode('utf-8', errors='replace').strip()
        raise RuntimeError(f"PowerShell toast failed (rc={result.returncode}): {stderr}")

    logger.info(f"Toast notification shown: {title}")


def _show_balloon_tip(title, message, app_name):
    """
    Fallback: show a system tray balloon tip notification.
    Works on older Windows versions and doesn't require WinRT.
    """
    safe_title = title.replace("'", "''")
    safe_message = message.replace("'", "''")

    ps_script = f"""
Add-Type -AssemblyName System.Windows.Forms
$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Icon = [System.Drawing.SystemIcons]::Information
$notify.Visible = $true
$notify.BalloonTipTitle = '{safe_title}'
$notify.BalloonTipText = '{safe_message}'
$notify.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::Info
$notify.ShowBalloonTip(10000)
Start-Sleep -Seconds 10
$notify.Dispose()
"""

    subprocess.Popen(
        ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_script],
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
    )

    logger.info(f"Balloon tip notification shown: {title}")
