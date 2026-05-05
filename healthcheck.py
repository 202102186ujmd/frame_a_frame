#!/usr/bin/env python3
"""
healthcheck.py – standalone script used by Docker HEALTHCHECK.

Exits 0 if the /health endpoint returns HTTP 200, exits 1 otherwise.
Usage:
    python healthcheck.py
"""

from __future__ import annotations

import os
import sys
import urllib.request

port = int(os.environ.get("HTTP_PORT", "8080"))
url = f"http://localhost:{port}/health"

try:
    urllib.request.urlopen(url, timeout=4)
    sys.exit(0)
except Exception as exc:
    print(f"healthcheck failed: {exc}", file=sys.stderr)
    sys.exit(1)
