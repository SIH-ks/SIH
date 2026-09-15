"""Structured request logging with a correlation id.

Every request gets an ``X-Request-ID`` (echoed back on the response, and reused if
the caller supplied one so a trace survives a reverse proxy). Every log line emitted
while handling that request carries it. In a land-records system this is not
housekeeping: when a Tehsildar reports that an approval did not stick, the audit
trail says *what* changed and this says *which request* did it.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

__all__ = ["RequestContextMiddleware", "configure_logging", "get_logger"]

REQUEST_ID_HEADER = "X-Request-ID"


def configure_logging(*, json_output: bool) -> None:
    """Wire structlog once, at application start.

    ``json_output`` is driven by environment rather than a separate flag: a developer
    reading a terminal wants colour and alignment, and a log shipper wants one JSON
    object per line. Both are the same events.
    """
    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer = (
        structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer(colors=True)
    )
    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind a request id (and the authenticated user, once known) to the log context.

    The user is bound by the auth dependency rather than here, because at middleware
    time the token has not been parsed yet -- ``structlog.contextvars`` is what lets
    that later binding still land on the same request's log lines.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:16]
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        request.state.request_id = request_id

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            get_logger("adhikar.request").exception(
                "request_failed", duration_ms=round((time.perf_counter() - started) * 1000, 2)
            )
            raise

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers[REQUEST_ID_HEADER] = request_id
        # /metrics and /health are polled continuously by Prometheus and by the
        # frontend's status pill; logging them would drown every line that matters.
        if request.url.path not in {"/metrics", "/health"}:
            get_logger("adhikar.request").info(
                "request", status_code=response.status_code, duration_ms=duration_ms
            )
        return response
