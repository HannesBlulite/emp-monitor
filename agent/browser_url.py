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
    Extract the URL from a browser window's address bar.
    Tries UIA first, then falls back to Win32 IAccessible (MSAA).

    Args:
        hwnd: The window handle of the browser window.

    Returns:
        The URL string, or empty string if extraction fails.
    """
    # Strategy 1: UI Automation via comtypes
    url = _get_url_via_uia(hwnd)
    if url:
        return url

    # Strategy 2: Win32 IAccessible (MSAA) — works when UIA fails
    url = _get_url_via_msaa(hwnd)
    if url:
        return url

    return ''


def _get_url_via_uia(hwnd: int) -> str:
    """Try to extract URL using UI Automation."""
    try:
        import comtypes
        import comtypes.client

        # COM must be initialised per-thread; safe to call multiple times.
        comtypes.CoInitialize()

        # Generate type-library wrappers so we get the real IUIAutomation
        # interface (not a bare IUnknown pointer).
        comtypes.client.GetModule('UIAutomationCore.dll')
        from comtypes.gen.UIAutomationClient import (
            CUIAutomation,
            IUIAutomation,
        )
        uia = comtypes.CoCreateInstance(
            CUIAutomation._reg_clsid_,
            interface=IUIAutomation,
            clsctx=comtypes.CLSCTX_INPROC_SERVER,
        )

        element = uia.ElementFromHandle(hwnd)
        if not element:
            return ''

        return _find_address_bar_value(uia, element)

    except ImportError:
        logger.debug('comtypes not available')
        return ''
    except Exception as e:
        logger.debug(f'UIA URL extraction failed: {e}')
        return ''


def _get_url_via_msaa(hwnd: int) -> str:
    """Try to extract URL using Win32 IAccessible (MSAA) via oleacc."""
    try:
        # Ensure COM is initialised for this thread.
        try:
            import comtypes
            comtypes.CoInitialize()
        except ImportError:
            pass  # MSAA via ctypes may still work

        import ctypes
        import ctypes.wintypes
        from ctypes import oledll, byref, POINTER, c_long, c_uint

        oleacc = ctypes.windll.oleacc

        # OBJID_CLIENT = -4
        OBJID_CLIENT = c_long(-4)

        # Get IAccessible interface from the window
        acc = ctypes.POINTER(ctypes.c_void_p)()
        child_id = ctypes.c_long()

        result = oleacc.AccessibleObjectFromWindow(
            hwnd, OBJID_CLIENT,
            byref(ctypes.c_char_p(b'{618736e0-3c3d-11cf-810c-00aa00389b71}')),
            byref(acc),
        )

        if result != 0 or not acc:
            return ''

        # Use win32com if available for easier traversal
        try:
            import win32com.client
            accessible = win32com.client.Dispatch(acc)

            # Walk children looking for the address bar
            def _walk(obj, depth=0):
                if depth > 8:
                    return ''
                try:
                    name = obj.accName(0) or ''
                    value = obj.accValue(0) or ''
                    role = obj.accRole(0) if hasattr(obj, 'accRole') else 0

                    # Role 42 = ROLE_SYSTEM_TEXT (edit box)
                    name_lower = name.lower()
                    if (role == 42 or 'edit' in str(role).lower()) and value:
                        if _looks_like_url(value) and any(
                            h in name_lower for h in
                            ('address', 'url', 'location', 'omnibox')
                        ):
                            return value

                    # Recurse into children
                    count = obj.accChildCount
                    for i in range(1, min(count + 1, 30)):
                        try:
                            child = obj.accChild(i)
                            if child:
                                found = _walk(child, depth + 1)
                                if found:
                                    return found
                        except Exception:
                            continue
                except Exception:
                    pass
                return ''

            return _walk(accessible)
        except ImportError:
            logger.debug('win32com not available for MSAA fallback')
            return ''

    except Exception as e:
        logger.debug(f'MSAA URL extraction failed: {e}')
        return ''


def _find_address_bar_value(uia, element) -> str:
    """
    Search for the address bar within the browser UI tree.
    Uses the UIA Value pattern on the address bar control.
    Prioritises controls whose Name or AutomationId indicates an address bar.
    """
    try:
        UIA_ControlTypePropertyId = 30003
        UIA_EditControlTypeId = 50004
        UIA_ValuePatternId = 10002
        UIA_NamePropertyId = 30005
        UIA_AutomationIdPropertyId = 30011

        condition = uia.CreatePropertyCondition(
            UIA_ControlTypePropertyId, UIA_EditControlTypeId
        )

        # TreeScope_Descendants = 4
        found = element.FindAll(4, condition)
        if not found:
            return ''

        # Known address-bar identifiers (name or AutomationId substrings)
        _ADDR_HINTS = (
            'address', 'url', 'omnibox', 'urlbar', 'addressbar',
            'location', 'navigation', 'search or enter',
        )

        best_candidate = ''
        from comtypes import COMError
        from comtypes.gen.UIAutomationClient import IUIAutomationValuePattern

        for i in range(found.Length):
            child = found.GetElement(i)
            try:
                pattern = child.GetCurrentPattern(UIA_ValuePatternId)
                if not pattern:
                    continue

                try:
                    vp = pattern.QueryInterface(IUIAutomationValuePattern)
                    value = vp.CurrentValue
                except (AttributeError, COMError):
                    continue

                if not value or not _looks_like_url(value):
                    continue

                # Check if this control is specifically the address bar
                try:
                    name = (child.CurrentName or '').lower()
                except Exception:
                    name = ''
                try:
                    auto_id = (child.GetCurrentPropertyValue(UIA_AutomationIdPropertyId) or '').lower()
                except Exception:
                    auto_id = ''

                ident = name + ' ' + auto_id
                if any(hint in ident for hint in _ADDR_HINTS):
                    return value  # High confidence — return immediately

                # Keep as fallback
                if not best_candidate:
                    best_candidate = value
            except Exception:
                continue

        return best_candidate
    except Exception as e:
        logger.debug(f'Address bar search failed: {e}')
        return ''


# Common TLDs for URL validation (kept small for speed)
_VALID_TLDS = frozenset({
    'com', 'org', 'net', 'edu', 'gov', 'io', 'co', 'us', 'uk', 'de', 'fr',
    'za', 'au', 'ca', 'in', 'br', 'ru', 'nl', 'it', 'es', 'se', 'no', 'fi',
    'jp', 'kr', 'cn', 'hk', 'tw', 'sg', 'nz', 'mx', 'ar', 'cl', 'info',
    'biz', 'me', 'tv', 'app', 'dev', 'ai', 'cloud', 'online', 'site',
    'tech', 'store', 'shop', 'blog', 'xyz', 'top', 'icu', 'page', 'live',
    'pro', 'jobs', 'mobi', 'name', 'museum', 'travel', 'coop', 'aero',
    'africa', 'capetown', 'durban', 'joburg', 'eco', 'vet', 'law',
})

# Country-code second-level domains (e.g. co.za, org.uk)
_CC_SLDS = frozenset({
    'co.za', 'org.za', 'gov.za', 'ac.za', 'net.za', 'web.za',
    'co.uk', 'org.uk', 'ac.uk', 'gov.uk',
    'com.au', 'org.au', 'gov.au', 'edu.au',
    'co.nz', 'org.nz', 'co.in', 'com.br', 'co.kr', 'co.jp',
})


def _looks_like_url(text: str) -> bool:
    """Check if text looks like a URL or domain (with TLD validation)."""
    text = text.strip()
    if not text:
        return False
    # Reject non-http schemes (chrome-extension://, file://, etc.)
    if '://' in text and not text.startswith(('http://', 'https://')):
        return False
    # Has a scheme
    if text.startswith(('http://', 'https://')):
        return True
    # Reject if it has spaces or looks like a file path
    if ' ' in text or '\\' in text:
        return False
    # Reject file-like strings (UUID.pdf, etc.)
    if re.search(r'\.(pdf|doc|docx|xls|xlsx|exe|zip|png|jpg|txt)$', text, re.IGNORECASE):
        return False
    # Must have at least one dot
    if '.' not in text:
        return False
    # Split and validate TLD
    parts = text.rstrip('/').split('/')[0].split('.')  # strip path, get domain parts
    if len(parts) < 2:
        return False
    tld = parts[-1].lower()
    if tld not in _VALID_TLDS:
        return False
    # Check for known ccSLD patterns (e.g. co.za)
    if len(parts) >= 3:
        sld = f'{parts[-2].lower()}.{tld}'
        if sld in _CC_SLDS:
            return True
    # Basic sanity: TLD is valid and domain part is alphanumeric
    domain_part = parts[-2]
    if domain_part and domain_part.replace('-', '').isalnum():
        return True
    return False


def extract_domain(url_or_domain: str) -> str:
    """
    Extract the domain from a URL or domain string.

    Examples:
        'https://www.github.com/user/repo' -> 'github.com'
        'mail.google.com' -> 'mail.google.com'
        'https://portal.ddcsa.co.za/login' -> 'portal.ddcsa.co.za'
        'chrome-extension://xxx/https://site.com/page' -> 'site.com'
    """
    text = url_or_domain.strip()
    if not text:
        return ''

    # Chrome-extension URLs may embed the real URL after the extension ID
    if text.startswith('chrome-extension://'):
        match = re.search(r'https?://[^\s]+', text)
        if match:
            text = match.group(0)
        else:
            return ''

    # Reject other non-http schemes
    if '://' in text and not text.startswith(('http://', 'https://')):
        return ''

    # Add scheme if missing for urlparse to work
    if not text.startswith(('http://', 'https://')):
        text = 'https://' + text

    try:
        parsed = urlparse(text)
        hostname = parsed.hostname or ''
        if hostname.startswith('www.'):
            hostname = hostname[4:]
        return hostname.lower()
    except Exception:
        return ''
