"""
drone_worker.py – Playwright capture loop and staleness watchdog.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Dict, Optional

from playwright.async_api import async_playwright, BrowserContext, Page

from channel_store import stores
from drone_config import (
    CAPTURE_HEIGHT,
    CAPTURE_INTERVAL,
    CAPTURE_WIDTH,
    RECONNECT_DELAY,
)
from js_scripts import AUTOPLAY_JS, CAPTURE_FRAME_JS

log = logging.getLogger("frame_a_frame")


# ---------------------------------------------------------------------------
# Console-message handler
# ---------------------------------------------------------------------------
def _handle_console(drone_id: str, text: str) -> None:
    """Detect MediaMTX offline indicators in browser console messages."""
    lower = text.lower()
    if "stream not found" in lower or "error: stream not found, retrying" in lower:
        store = stores.get(drone_id)
        if store:
            store.update_state("offline", "stream not found")
        log.info("[%s] console → offline (stream not found)", drone_id)


# ---------------------------------------------------------------------------
# Drone worker
# ---------------------------------------------------------------------------
async def drone_worker(drone: Dict[str, str]) -> None:
    """Playwright loop that captures frames for one drone."""
    drone_id = drone["id"]
    url = drone["url"]
    store = stores[drone_id]
    log.info("[%s] worker starting, url=%s", drone_id, url)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--autoplay-policy=no-user-gesture-required",
                "--use-fake-ui-for-media-stream",
                "--ignore-certificate-errors",
            ],
        )

        while True:
            store.update_state("connecting")
            context: Optional[BrowserContext] = None
            page: Optional[Page] = None
            try:
                context = await browser.new_context(
                    viewport={"width": CAPTURE_WIDTH, "height": CAPTURE_HEIGHT},
                    ignore_https_errors=True,
                )
                page = await context.new_page()

                # Listen for console messages – detect MediaMTX offline text
                page.on(
                    "console",
                    lambda msg, d=drone_id: _handle_console(d, msg.text),
                )

                log.info("[%s] navigating to %s", drone_id, url)
                await page.goto(url, timeout=30_000, wait_until="domcontentloaded")

                # Attempt auto-play
                try:
                    await page.evaluate(AUTOPLAY_JS)
                except Exception:
                    pass

                # Wait a moment for the stream to initialise
                await asyncio.sleep(2)

                # ---- frame-capture loop ----
                while True:
                    try:
                        b64: str = await page.evaluate(CAPTURE_FRAME_JS)
                        jpeg = base64.b64decode(b64)
                        store.update_frame(jpeg)
                    except Exception as exc:
                        err = str(exc)
                        # Classify as offline when MediaMTX reports stream absent
                        if "stream not found" in err.lower():
                            store.update_state("offline", "stream not found")
                            log.info("[%s] offline – stream not found", drone_id)
                        else:
                            store.update_state("error", err[:200])
                            log.warning("[%s] capture error: %s", drone_id, err)

                    await asyncio.sleep(CAPTURE_INTERVAL)

            except asyncio.CancelledError:
                log.info("[%s] worker cancelled", drone_id)
                break
            except Exception as exc:
                store.update_state("error", str(exc)[:200])
                log.error("[%s] worker exception: %s", drone_id, exc)
            finally:
                if page is not None:
                    try:
                        await page.close()
                    except Exception:
                        pass
                if context is not None:
                    try:
                        await context.close()
                    except Exception:
                        pass

            log.info("[%s] reconnecting in %.0fs", drone_id, RECONNECT_DELAY)
            await asyncio.sleep(RECONNECT_DELAY)

        await browser.close()


# ---------------------------------------------------------------------------
# Staleness watchdog
# ---------------------------------------------------------------------------
async def staleness_watchdog() -> None:
    """Periodically marks channels as stale when no frames arrive within STALE_TIMEOUT."""
    while True:
        await asyncio.sleep(2)
        for store in stores.values():
            if store.is_stale and store.state == "online":
                store.update_state("stale", "no frame received recently")
