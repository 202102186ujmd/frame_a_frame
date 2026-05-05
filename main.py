"""
frame_a_frame – drone frame-capture service
============================================
Captures JPEG frames from MediaMTX WebRTC streams via Playwright + canvas,
and exposes them over HTTP (JPEG / MJPEG) and WebSocket.

Drone defaults:
  DC1001 → https://droneStream:***@droni.seguridad.sv:8889/Castillo001
  DC1002 → https://droneStream:***@droni.seguridad.sv:8889/Mjsp002
  DC1003 → https://droneStream:***@droni.seguridad.sv:8889/DCI003

Environment variables (see .env.example for full list):
  DRONE_DC1001_URL / DRONE_DC1002_URL / DRONE_DC1003_URL  – stream URLs
  HTTP_HOST / HTTP_PORT                                   – server binding
  SSL_CERT / SSL_KEY                                      – optional TLS
  CAPTURE_FPS / CAPTURE_WIDTH / CAPTURE_HEIGHT
  RECONNECT_DELAY / STALE_TIMEOUT
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from typing import Dict, List, Optional, Set

from aiohttp import web
from playwright.async_api import async_playwright, BrowserContext, Page

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("frame_a_frame")

# ---------------------------------------------------------------------------
# Configuration – defaults come from environment, with hard-coded fallbacks
# ---------------------------------------------------------------------------
_DEFAULT_DRONES = [
    {
        "id": "DC1001",
        "url": "https://droneStream:KHlQlNfZVPtjg4a09Rn9Vo@droni.seguridad.sv:8889/Castillo001",
    },
    {
        "id": "DC1002",
        "url": "https://droneStream:KHlQlNfZVPtjg4a09Rn9Vo@droni.seguridad.sv:8889/Mjsp002",
    },
    {
        "id": "DC1003",
        "url": "https://droneStream:KHlQlNfZVPtjg4a09Rn9Vo@droni.seguridad.sv:8889/DCI003",
    },
]

HTTP_HOST = os.environ.get("HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.environ.get("HTTP_PORT", "8080"))
SSL_CERT = os.environ.get("SSL_CERT", "").strip()
SSL_KEY = os.environ.get("SSL_KEY", "").strip()
CAPTURE_FPS = float(os.environ.get("CAPTURE_FPS", "1"))
CAPTURE_WIDTH = int(os.environ.get("CAPTURE_WIDTH", "1280"))
CAPTURE_HEIGHT = int(os.environ.get("CAPTURE_HEIGHT", "720"))
RECONNECT_DELAY = float(os.environ.get("RECONNECT_DELAY", "5"))
STALE_TIMEOUT = float(os.environ.get("STALE_TIMEOUT", "10"))

CAPTURE_INTERVAL = 1.0 / max(CAPTURE_FPS, 0.1)

# Override drone URLs from environment if provided
def _build_drone_list() -> List[Dict[str, str]]:
    drones: List[Dict[str, str]] = []
    for d in _DEFAULT_DRONES:
        env_key = f"DRONE_{d['id']}_URL"
        url = os.environ.get(env_key, d["url"]).strip()
        drones.append({"id": d["id"], "url": url})
    return drones

DRONES = _build_drone_list()

# ---------------------------------------------------------------------------
# JS snippet injected into every captured page
# ---------------------------------------------------------------------------
# Returns a base-64 JPEG string from the first <video> element, or raises
# an error string (prefixed with "Error:") if video is not ready / offline.
CAPTURE_FRAME_JS = """
() => {
    // Detect MediaMTX "stream not found" message in the page text
    const bodyText = document.body ? document.body.innerText : '';
    if (bodyText.includes('stream not found')) {
        throw new Error('stream not found, retrying in some seconds');
    }

    const video = document.querySelector('video');
    if (!video) {
        throw new Error('no video element found');
    }
    if (video.readyState < 2) {
        throw new Error('video not ready (readyState=' + video.readyState + ')');
    }
    if (video.videoWidth === 0 || video.videoHeight === 0) {
        throw new Error('video has zero dimensions');
    }

    const canvas = document.createElement('canvas');
    canvas.width  = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', 0.85).split(',')[1];
}
"""

# JS to inject into MediaMTX pages to auto-play the video element
AUTOPLAY_JS = """
() => {
    const video = document.querySelector('video');
    if (video) {
        video.muted = true;
        video.play().catch(() => {});
    }
}
"""

# ---------------------------------------------------------------------------
# Channel store – holds latest frame + notifies subscribers
# ---------------------------------------------------------------------------
_VALID_STATES = {"connecting", "online", "offline", "stale", "error"}


class ChannelStore:
    """Holds the latest JPEG bytes and connection state for one drone channel."""

    def __init__(self, drone_id: str):
        self.drone_id = drone_id
        self.state: str = "connecting"
        self.last_frame: Optional[bytes] = None
        self.last_frame_ts: float = 0.0
        self.error_msg: str = ""
        self._event: asyncio.Event = asyncio.Event()
        self._ws_clients: Set[web.WebSocketResponse] = set()

    # ------------------------------------------------------------------
    def update_frame(self, jpeg: bytes) -> None:
        self.last_frame = jpeg
        self.last_frame_ts = time.monotonic()
        self.state = "online"
        self.error_msg = ""
        self._event.set()
        self._event.clear()
        asyncio.ensure_future(self._broadcast_frame(jpeg))

    def update_state(self, state: str, msg: str = "") -> None:
        assert state in _VALID_STATES, f"unknown state {state!r}"
        self.state = state
        self.error_msg = msg
        asyncio.ensure_future(self._broadcast_status())

    # ------------------------------------------------------------------
    async def wait_for_frame(self) -> None:
        await self._event.wait()

    # ------------------------------------------------------------------
    def register_ws(self, ws: web.WebSocketResponse) -> None:
        self._ws_clients.add(ws)

    def unregister_ws(self, ws: web.WebSocketResponse) -> None:
        self._ws_clients.discard(ws)

    # ------------------------------------------------------------------
    async def _broadcast_frame(self, jpeg: bytes) -> None:
        b64 = base64.b64encode(jpeg).decode()
        msg = f'{{"type":"frame","drone":"{self.drone_id}","data":"{b64}"}}'
        await self._send_to_all(msg)

    async def _broadcast_status(self) -> None:
        msg = (
            f'{{"type":"status","drone":"{self.drone_id}",'
            f'"state":"{self.state}","msg":"{self.error_msg}"}}'
        )
        await self._send_to_all(msg)

    async def _send_to_all(self, msg: str) -> None:
        dead: list = []
        for ws in list(self._ws_clients):
            try:
                await ws.send_str(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._ws_clients.discard(ws)

    # ------------------------------------------------------------------
    @property
    def is_stale(self) -> bool:
        if self.last_frame_ts == 0:
            return False
        return (time.monotonic() - self.last_frame_ts) > STALE_TIMEOUT


# ---------------------------------------------------------------------------
# Store registry
# ---------------------------------------------------------------------------
stores: Dict[str, ChannelStore] = {d["id"]: ChannelStore(d["id"]) for d in DRONES}


# ---------------------------------------------------------------------------
# Drone worker – Playwright loop
# ---------------------------------------------------------------------------
async def drone_worker(drone: Dict[str, str]) -> None:
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

                # Wait a moment for stream to initialise
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


def _handle_console(drone_id: str, text: str) -> None:
    """Handle browser console messages, detecting MediaMTX offline indicators."""
    lower = text.lower()
    if "stream not found" in lower:
        store = stores.get(drone_id)
        if store:
            store.update_state("offline", "stream not found")
        log.info("[%s] console → offline (stream not found)", drone_id)


# ---------------------------------------------------------------------------
# Staleness watchdog task
# ---------------------------------------------------------------------------
async def staleness_watchdog() -> None:
    while True:
        await asyncio.sleep(2)
        for store in stores.values():
            if store.is_stale and store.state == "online":
                store.update_state("stale", "no frame received recently")


# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------
async def handle_frame_jpg(request: web.Request) -> web.Response:
    """Return the latest JPEG frame for a drone. 404 if no frame yet."""
    drone_id = request.match_info["drone_id"]
    store = stores.get(drone_id)
    if store is None:
        raise web.HTTPNotFound(text=f"unknown drone: {drone_id}")
    if store.last_frame is None:
        raise web.HTTPServiceUnavailable(text="no frame available yet")
    return web.Response(
        body=store.last_frame,
        content_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


async def handle_mjpeg_stream(request: web.Request) -> web.StreamResponse:
    """Push an MJPEG stream for a drone."""
    drone_id = request.match_info["drone_id"]
    store = stores.get(drone_id)
    if store is None:
        raise web.HTTPNotFound(text=f"unknown drone: {drone_id}")

    boundary = b"--frame"
    response = web.StreamResponse(
        headers={
            "Content-Type": f"multipart/x-mixed-replace; boundary=frame",
            "Cache-Control": "no-store",
        }
    )
    await response.prepare(request)

    try:
        while True:
            if store.last_frame:
                part = (
                    boundary
                    + b"\r\nContent-Type: image/jpeg\r\n\r\n"
                    + store.last_frame
                    + b"\r\n"
                )
                await response.write(part)
            await asyncio.sleep(CAPTURE_INTERVAL)
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    return response


async def handle_status(request: web.Request) -> web.Response:
    """Return JSON status for a single drone or all drones."""
    drone_id = request.match_info.get("drone_id")
    if drone_id:
        store = stores.get(drone_id)
        if store is None:
            raise web.HTTPNotFound(text=f"unknown drone: {drone_id}")
        return web.json_response(
            {
                "drone": drone_id,
                "state": store.state,
                "msg": store.error_msg,
                "has_frame": store.last_frame is not None,
                "last_frame_age": (
                    round(time.monotonic() - store.last_frame_ts, 1)
                    if store.last_frame_ts
                    else None
                ),
            }
        )
    # All drones
    result = []
    for s in stores.values():
        result.append(
            {
                "drone": s.drone_id,
                "state": s.state,
                "msg": s.error_msg,
                "has_frame": s.last_frame is not None,
            }
        )
    return web.json_response(result)


async def handle_healthcheck(request: web.Request) -> web.Response:
    online = sum(1 for s in stores.values() if s.state in ("online", "stale"))
    return web.json_response({"status": "ok", "online": online, "total": len(stores)})


async def handle_websocket(request: web.Request) -> web.WebSocketResponse:
    """WebSocket: sends frames and status updates for all drones."""
    ws = web.WebSocketResponse(heartbeat=15)
    await ws.prepare(request)

    # Subscribe to all drones
    for store in stores.values():
        store.register_ws(ws)
        # Send current state immediately
        await ws.send_str(
            f'{{"type":"status","drone":"{store.drone_id}",'
            f'"state":"{store.state}","msg":"{store.error_msg}"}}'
        )

    try:
        async for _ in ws:
            pass  # client messages are ignored
    finally:
        for store in stores.values():
            store.unregister_ws(ws)

    return ws


async def handle_index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(
        path=os.path.join(os.path.dirname(__file__), "static", "index.html")
    )


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/ws", handle_websocket)
    app.router.add_get("/health", handle_healthcheck)
    app.router.add_get("/status", handle_status)
    app.router.add_get("/status/{drone_id}", handle_status)
    app.router.add_get("/{drone_id}/frame.jpg", handle_frame_jpg)
    app.router.add_get("/{drone_id}/stream.mjpg", handle_mjpeg_stream)
    app.router.add_static("/static", path=os.path.join(os.path.dirname(__file__), "static"))
    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main() -> None:
    app = build_app()

    # SSL context (optional)
    ssl_context = None
    if SSL_CERT and SSL_KEY:
        import ssl
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain(certfile=SSL_CERT, keyfile=SSL_KEY)
        log.info("SSL enabled: cert=%s key=%s", SSL_CERT, SSL_KEY)
    else:
        log.info("SSL disabled (set SSL_CERT and SSL_KEY to enable HTTPS/WSS)")

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HTTP_HOST, HTTP_PORT, ssl_context=ssl_context)
    await site.start()

    proto = "https" if ssl_context else "http"
    log.info("Server listening on %s://%s:%d", proto, HTTP_HOST, HTTP_PORT)
    for d in DRONES:
        log.info("  Drone %s → %s", d["id"], d["url"])

    # Launch workers + watchdog
    tasks = [asyncio.create_task(drone_worker(d)) for d in DRONES]
    tasks.append(asyncio.create_task(staleness_watchdog()))

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        for t in tasks:
            t.cancel()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
