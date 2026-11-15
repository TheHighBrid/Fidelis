"""Standard-library-only local HTTP request validation."""

import ipaddress
from urllib.parse import urlparse


def require_local_request(handler):
    """Reject non-loopback, hostile-host, and cross-origin browser requests."""
    if not ipaddress.ip_address(handler.client_address[0]).is_loopback:
        raise PermissionError("Regional workspace accepts loopback clients only")
    host = handler.headers.get("Host", "")
    parsed = urlparse("http://" + host)
    if parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise PermissionError("Regional workspace is available through localhost only")
    origin = handler.headers.get("Origin")
    if origin is not None and origin != "http://" + host:
        raise PermissionError("Cross-origin workspace access is not allowed")
