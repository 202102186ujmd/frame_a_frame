"""
drone_config.py – centralised configuration for frame_a_frame.

All tuneable values are read from environment variables.  Hard-coded
defaults are used when an env-var is absent (see .env.example).
"""

from __future__ import annotations

import os
from typing import Dict, List

# ---------------------------------------------------------------------------
# Default drone definitions
# ---------------------------------------------------------------------------
_DEFAULT_DRONES: List[Dict[str, str]] = [
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

# ---------------------------------------------------------------------------
# HTTP / WebSocket server
# ---------------------------------------------------------------------------
HTTP_HOST: str = os.environ.get("HTTP_HOST", "0.0.0.0")
HTTP_PORT: int = int(os.environ.get("HTTP_PORT", "8080"))

# ---------------------------------------------------------------------------
# SSL – leave blank to run plain HTTP/WS
# ---------------------------------------------------------------------------
SSL_CERT: str = os.environ.get("SSL_CERT", "").strip()
SSL_KEY: str = os.environ.get("SSL_KEY", "").strip()

# ---------------------------------------------------------------------------
# Capture settings
# ---------------------------------------------------------------------------
CAPTURE_FPS: float = float(os.environ.get("CAPTURE_FPS", "1"))
CAPTURE_WIDTH: int = int(os.environ.get("CAPTURE_WIDTH", "1280"))
CAPTURE_HEIGHT: int = int(os.environ.get("CAPTURE_HEIGHT", "720"))

CAPTURE_INTERVAL: float = 1.0 / max(CAPTURE_FPS, 0.1)

# ---------------------------------------------------------------------------
# Reconnect / staleness
# ---------------------------------------------------------------------------
RECONNECT_DELAY: float = float(os.environ.get("RECONNECT_DELAY", "5"))
STALE_TIMEOUT: float = float(os.environ.get("STALE_TIMEOUT", "10"))


# ---------------------------------------------------------------------------
# Build the active drone list (env overrides take precedence)
# ---------------------------------------------------------------------------
def _build_drone_list() -> List[Dict[str, str]]:
    drones: List[Dict[str, str]] = []
    for d in _DEFAULT_DRONES:
        env_key = f"DRONE_{d['id']}_URL"
        url = os.environ.get(env_key, d["url"]).strip()
        drones.append({"id": d["id"], "url": url})
    return drones


DRONES: List[Dict[str, str]] = _build_drone_list()
