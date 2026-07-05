"""
app/core/request_context.py
=============================
Per-request context propagation using Python contextvars.

The RequestContextMiddleware (app/main.py) populates these variables once per
incoming HTTP request.  audit_log_service.record() reads them as automatic
defaults so every audit row gets the real client IP + user-agent without any
change to route handlers or service call sites.

IP extraction precedence
------------------------
1. X-Forwarded-For  (first / leftmost value — original client behind proxy)
2. X-Real-IP        (nginx / load-balancer single-header variant)
3. request.client.host  (direct socket — fallback for local / Docker dev)
"""

from __future__ import annotations

from contextvars import ContextVar

# Reset to None at the start of every request by the middleware.
_request_ip: ContextVar[str | None] = ContextVar("_request_ip", default=None)
_request_ua: ContextVar[str | None] = ContextVar("_request_ua", default=None)


def set_request_context(ip: str | None, user_agent: str | None) -> None:
    """Called once per request by RequestContextMiddleware."""
    _request_ip.set(ip)
    _request_ua.set(user_agent)


def get_request_ip() -> str | None:
    """Return the IP address for the current request, or None."""
    return _request_ip.get()


def get_request_ua() -> str | None:
    """Return the User-Agent string for the current request, or None."""
    return _request_ua.get()
