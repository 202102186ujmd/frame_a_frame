"""
channel_store.py – per-drone frame buffer and subscriber registry.
"""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Dict, Optional, Set

from aiohttp import web

from drone_config import DRONES, STALE_TIMEOUT

_VALID_STATES = {"connecting", "online", "offline", "stale", "error"}


class ChannelStore:
    """Holds the latest JPEG bytes and connection state for one drone channel."""

    def __init__(self, drone_id: str) -> None:
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
# Global store registry – one entry per drone, created at import time
# ---------------------------------------------------------------------------
stores: Dict[str, ChannelStore] = {d["id"]: ChannelStore(d["id"]) for d in DRONES}
