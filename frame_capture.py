#!/usr/bin/env python3
"""
frame_capture.py – entry point for the frame_a_frame drone service.
====================================================================
Starts the aiohttp HTTP/WebSocket server and one Playwright capture
worker per configured drone.

Quick-start:
    python frame_capture.py

With Docker / pm2:
    CMD ["python", "frame_capture.py"]
    pm2 start frame_capture.py --interpreter python3

See README.md and .env.example for configuration options.
"""

from __future__ import annotations

# Configure logging before any other local imports so module-level loggers
# inside the other modules pick up the format defined in setup_logging().
from utils import setup_logging

setup_logging()

import asyncio
import logging
import ssl

from aiohttp import web

from drone_config import DRONES, HTTP_HOST, HTTP_PORT, SSL_CERT, SSL_KEY
from drone_worker import drone_worker, staleness_watchdog
from servers.http_server import build_app

log = logging.getLogger("frame_a_frame")


async def main() -> None:
    app = build_app()

    # SSL context (optional – set SSL_CERT and SSL_KEY env vars to enable)
    ssl_context = None
    if SSL_CERT and SSL_KEY:
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain(certfile=SSL_CERT, keyfile=SSL_KEY)
        log.info("SSL enabled: cert=%s  key=%s", SSL_CERT, SSL_KEY)
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

    # Launch one worker per drone plus the staleness watchdog
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
