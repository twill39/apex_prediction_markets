"""Shared HTTP helpers for discovery (SSL, GET JSON)."""

import json
import ssl
import urllib.request
from typing import Any, Optional

try:
    import certifi
except ImportError:
    certifi = None


def ssl_context() -> ssl.SSLContext:
    """SSL context using certifi CA bundle when available."""
    ctx = ssl.create_default_context()
    if certifi is not None:
        ctx.load_verify_locations(certifi.where())
    return ctx


def get_json(url: str, timeout: int = 15) -> Optional[Any]:
    """GET URL and parse JSON. Returns None on failure."""
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None
