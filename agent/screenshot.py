"""
Screenshot Capture Module
Captures screenshots from all connected monitors using the mss library.
"""

import io
import os
import time
import logging
from datetime import datetime

import mss
from PIL import Image

logger = logging.getLogger('emp_agent.screenshot')


def capture_all_monitors(quality=60, image_format='JPEG'):
    """
    Capture screenshots from all connected monitors.

    Returns a list of dicts:
        [
            {
                'monitor_index': 1,
                'image_bytes': b'...',
                'width': 1920,
                'height': 1080,
                'timestamp': '2026-02-21T05:30:00'
            },
            ...
        ]
    """
    screenshots = []
    timestamp = datetime.now().isoformat()

    try:
        with mss.mss() as sct:
            # sct.monitors[0] is the "all monitors" virtual screen
            # sct.monitors[1], [2], etc. are individual monitors
            monitors = sct.monitors[1:]  # skip the combined virtual monitor

            logger.info(f"Detected {len(monitors)} monitor(s)")

            for idx, monitor in enumerate(monitors, start=1):
                try:
                    # Capture the monitor
                    sct_img = sct.grab(monitor)

                    # Convert to PIL Image
                    img = Image.frombytes('RGB', sct_img.size, sct_img.bgra, 'raw', 'BGRX')

                    # Compress to bytes
                    buffer = io.BytesIO()
                    if image_format.upper() == 'JPEG':
                        img.save(buffer, format='JPEG', quality=quality, optimize=True)
                    elif image_format.upper() == 'WEBP':
                        img.save(buffer, format='WEBP', quality=quality)
                    else:
                        img.save(buffer, format='PNG')

                    image_bytes = buffer.getvalue()
                    buffer.close()

                    screenshots.append({
                        'monitor_index': idx,
                        'image_bytes': image_bytes,
                        'width': monitor['width'],
                        'height': monitor['height'],
                        'timestamp': timestamp,
                    })

                    logger.debug(
                        f"Monitor {idx}: {monitor['width']}x{monitor['height']} "
                        f"-> {len(image_bytes)} bytes"
                    )

                except Exception as e:
                    logger.error(f"Failed to capture monitor {idx}: {e}")
                    continue

    except Exception as e:
        logger.error(f"Screenshot capture failed: {e}")

    return screenshots


def save_screenshots_locally(screenshots, output_dir='screenshots_queue'):
    """
    Save screenshots to local disk as a fallback when server is unreachable.
    Returns list of saved file paths.
    """
    os.makedirs(output_dir, exist_ok=True)
    saved_paths = []

    for shot in screenshots:
        filename = (
            f"screenshot_mon{shot['monitor_index']}_"
            f"{shot['timestamp'].replace(':', '-').replace('T', '_')}.jpg"
        )
        filepath = os.path.join(output_dir, filename)

        try:
            with open(filepath, 'wb') as f:
                f.write(shot['image_bytes'])
            saved_paths.append(filepath)
            logger.debug(f"Saved locally: {filepath}")
        except Exception as e:
            logger.error(f"Failed to save screenshot locally: {e}")

    return saved_paths


if __name__ == '__main__':
    # Quick test: capture and save screenshots
    logging.basicConfig(level=logging.DEBUG)
    shots = capture_all_monitors(quality=60)
    print(f"Captured {len(shots)} screenshot(s)")
    paths = save_screenshots_locally(shots, output_dir='test_screenshots')
    for p in paths:
        print(f"  Saved: {p}")
