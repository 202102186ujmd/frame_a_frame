"""
http_server.py – aiohttp HTTP handlers and app factory for frame_a_frame.
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
import time

from aiohttp import web

from channel_store import stores
from drone_config import CAPTURE_INTERVAL
from servers.html_templates import INDEX_HTML
from servers.ws_server import handle_websocket

log = logging.getLogger("frame_a_frame")

# Absolute path to the static/ directory (one level above this file)
_STATIC_DIR = str(pathlib.Path(__file__).parent.parent / "static")


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
async def handle_frame_jpg(request: web.Request) -> web.Response:
    """Return the latest JPEG frame for a drone. 404 if drone unknown."""
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
            "Content-Type": "multipart/x-mixed-replace; boundary=frame",
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


async def handle_index(request: web.Request) -> web.Response:
    return web.Response(text=INDEX_HTML, content_type="text/html")


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
    app.router.add_static("/static", path=_STATIC_DIR)
    return app
