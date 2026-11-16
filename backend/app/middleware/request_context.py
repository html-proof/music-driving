import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

log = logging.getLogger("app.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Adds an X-Request-ID header and logs one structured line per request."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("request_failed id=%s %s %s", request_id, request.method, request.url.path)
            raise
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        log.info("id=%s method=%s path=%s status=%s duration_ms=%.1f", request_id, request.method,
                 request.url.path, response.status_code, elapsed_ms)
        return response
