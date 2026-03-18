"""
Browser URL Extraction Module

Extracts the current URL from the active browser window using
Windows UI Automation (via comtypes + UIAutomationCore).

Supported browsers: Chrome, Edge, Firefox, Brave, Opera.
"""

import logging
import re
from urllib.parse import urlparse

logger = logging.getLogger('emp_agent.browser_url')

# Known browser process names (lowercase, without .exe)
BROWSER_PROCESSES = {
    'chrome', 'msedge', 'firefox', 'brave', 'opera', 'iexplore',
    'chromium', 'vivaldi', 'waterfox', 'librewolf',
}


def is_browser_process(process_name: str) -> bool:
    """Check if a process name is a known browser."""
    name = process_name.lower().replace('.exe', '')
    return name in BROWSER_PROCESSES


def extract_domain_from_title(window_title: str, process_name: str) -> str:
    """
    Fallback: try to extract a domain from the browser window title.

    Browser titles typically look like:
        "Page Title - Google Chrome"
        "Page Title — Mozilla Firefox"
        "Page Title - sitename.com - Google Chrome"

    This is a best-effort heuristic when UI Automation fails.
    """
    if not window_title or not is_browser_process(process_name):
        return ''

    # Remove browser suffix (e.g. " - Google Chrome", " — Mozilla Firefox")
    browser_suffixes = [
        r'\s*[-–—]\s*Google Chrome$',
        r'\s*[-–—]\s*Microsoft\u200b? Edge$',
        r'\s*[-–—]\s*Mozilla Firefox$',
        r'\s*[-–—]\s*Brave$',
        r'\s*[-–—]\s*Opera$',
        r'\s*[-–—]\s*Vivaldi$',
        r'\s*[-–—]\s*Chromium$',
    ]
    title = window_title
    for suffix in browser_suffixes:
        title = re.sub(suffix, '', title, flags=re.IGNORECASE)

    # Look for a domain-like pattern in the remaining title
    domain_pattern = r'(?:https?://)?([a-zA-Z0-9][-a-zA-Z0-9]*(?:\.[a-zA-Z0-9][-a-zA-Z0-9]*)+)'
    match = re.search(domain_pattern, title)
    if match:
        return match.group(1).lower()

    return ''


def get_browser_url(hwnd: int) -> str:
    """
    Extract the URL from a browser window's address bar using UI Automation.

    Args:
        hwnd: The window handle of the browser window.

    Returns:
        The URL string, or empty string if extraction fails.
    """
    try:
        import comtypes.client as cc

        # Initialize UI Automation
        uia = cc.CreateObject(
            '{ff48dba4-60ef-4201-aa87-54103eef594e}',
            interface=None,
        )

        # Get the element from the window handle
        element = uia.ElementFromHandle(hwnd)
        if not element:
            return ''

        # Search for the address bar using various strategies
        url = _find_address_bar_value(uia, element)
        return url

    except ImportError:
        logger.debug('comtypes not available — falling back to title extraction')
        return ''
    except Exception as e:
        logger.debug(f'UI Automation URL extraction failed: {e}')
        return ''


def _find_address_bar_value(uia, element) -> str:
    """
    Search for the address bar within the browser UI tree.
    Uses the UIA Value pattern on the address bar control.
    """
    try:
        # Create condition for Edit controls (address bar is typically an Edit)
        UIA_ControlTypePropertyId = 30003
        UIA_EditControlTypeId = 50004
        UIA_ValuePatternId = 10002

        condition = uia.CreatePropertyCondition(
            UIA_ControlTypePropertyId, UIA_EditControlTypeId
        )

        # Find all edit controls
        # TreeScope_Descendants = 4
        found = element.FindAll(4, condition)
        if not found:
            return ''

        for i in range(found.Length):
            child = found.GetElement(i)
            try:
                # Try to get the Value pattern
                pattern = child.GetCurrentPattern(UIA_ValuePatternId)
                if pattern:
                    # QI for IUIAutomationValuePattern
                    from comtypes import COMError
                    try:
                        value = pattern.CurrentValue
                        if value and _looks_like_url(value):
                            return value
                    except (AttributeError, COMError):
                        continue
            except Exception:
                continue

        return ''
    except Exception as e:
        logger.debug(f'Address bar search failed: {e}')
        return ''


def _looks_like_url(text: str) -> bool:
    """Check if text looks like a URL or domain."""
    text = text.strip()
    if not text:
        return False
    # Has a scheme
    if text.startswith(('http://', 'https://', 'ftp://')):
        return True
    # Looks like a domain (has at least one dot, no spaces)
    if ' ' not in text and '.' in text:
        parts = text.split('.')
        if len(parts) >= 2 and all(p.replace('-', '').isalnum() for p in parts if p):
            return True
    return False


def extract_domain(url_or_domain: str) -> str:
    """
    Extract the domain from a URL or domain string.

    Examples:
        'https://www.github.com/user/repo' -> 'github.com'
        'mail.google.com' -> 'mail.google.com'
        'https://portal.ddcsa.co.za/login' -> 'portal.ddcsa.co.za'
    """
    text = url_or_domain.strip()
    if not text:
        return ''

    # Add scheme if missing for urlparse to work
    if not text.startswith(('http://', 'https://', 'ftp://')):
        text = 'https://' + text

    try:
        parsed = urlparse(text)
        hostname = parsed.hostname or ''
        # Remove 'www.' prefix for matching
        if hostname.startswith('www.'):
            hostname = hostname[4:]
        return hostname.lower()
    except Exception:
        return ''
