"""Errors the API turns into JSON responses: {"detail": "...", "code": "..."}."""

from __future__ import annotations


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class StreamUnavailable(AppError):
    """The song exists but the provider returned no playable audio stream."""

    status_code = 404
    code = "stream_unavailable"


class ProviderUnavailable(AppError):
    """Gaana is unreachable, blocking us, or returned a server error."""

    status_code = 503
    code = "provider_unavailable"


class InvalidInput(AppError):
    status_code = 400
    code = "invalid_input"
