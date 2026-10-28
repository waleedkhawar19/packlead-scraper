"""Structured (key=value) logging to stdout - easy to read locally and to parse on hosting platforms."""
import logging
import sys

from app.config import get_settings


def setup_logging() -> None:
    level = getattr(logging, get_settings().log_level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter('ts=%(asctime)s level=%(levelname)s logger=%(name)s msg="%(message)s"', "%Y-%m-%dT%H:%M:%S")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for noisy in ("httpx", "httpcore", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
