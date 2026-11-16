class Errors:
    async def invalid_seokey(self) -> dict:
        return {"error": "Invalid Seokey!"}
    async def no_results(self) -> dict:
        return {"error": "Unable to find any results!"}


class UpstreamError(Exception):
    """Gaana could not be reached or refused the request (see app.py for the HTTP mapping)."""


class BlockedError(UpstreamError):
    """Gaana refused the request (401/403/429), or GaanaPy's circuit breaker is open.

    Answered as 503 {"error": "blocked", "upstream_status", "retry_after"} by app.py.
    """

    def __init__(self, status: int, retry_after: int):
        super().__init__(f"Gaana refused the request (HTTP {status}); retry in {retry_after} s")
        self.status = status
        self.retry_after = retry_after


class UpstreamUnavailable(UpstreamError):
    """Network error, timeout or 5xx from Gaana. Answered as 502 by app.py."""


def most_severe(failures: list) -> Exception:
    """The failure to report when every request of a fan-out failed: a block wins."""
    for failure in failures:
        if isinstance(failure, BlockedError):
            return failure
    return failures[0]
