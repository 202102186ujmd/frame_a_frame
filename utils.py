"""
utils.py – shared utilities for frame_a_frame.
"""

from __future__ import annotations

import logging


def setup_logging() -> None:
    """Configure root logging.  Call once from the entry point before other imports log."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
