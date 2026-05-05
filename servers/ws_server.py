"""
ws_server.py – WebSocket handler for frame_a_frame.

Broadcasts JPEG frames (base-64) and status updates for all drones to
every connected WebSocket client.
"""

from __future__ import annotations

import logging

from aiohttp import web

from channel_store import stores

log = logging.getLogger("frame_a_frame")


async def handle_websocket(request: web.Request) -> web.WebSocketResponse:
    """WebSocket: sends frames and status updates for all drones."""
    ws = web.WebSocketResponse(heartbeat=15)
    await ws.prepare(request)

    # Subscribe to all drones and send current state immediately
    for store in stores.values():
        store.register_ws(ws)
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
