"""Local fix: request layer (headers, circuit breaker, pacing, list cache, error kinds).

Offline: aiohttp's session is replaced by a fake; nothing is sent to Gaana.
"""

import asyncio
import json
import time

import aiohttp
import pytest
import pytest_asyncio
from yarl import URL

from api import endpoints
from api.errors import BlockedError, UpstreamUnavailable
from api.gaanapy import GaanaPy
from api.upstream import CircuitBreaker, Pacer, ResponseCache


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None, raw=None):
        self.status = status
        self.headers = headers or {}
        self._raw = raw if raw is not None else json.dumps(body if body is not None else {}).encode()

    async def read(self):
        return self._raw

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Records every request; answers from a list of responses (or exceptions)."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        answer = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def close(self):
        pass


@pytest_asyncio.fixture(loop_scope="function")
async def gaana():
    g = GaanaPy()
    await g.aiohttp.close()
    yield g


def use(g, *responses) -> FakeSession:
    g.aiohttp = FakeSession(*responses)
    return g.aiohttp


@pytest.mark.asyncio
async def test_requests_do_not_impersonate_a_browser(gaana):
    session = use(gaana, FakeResponse(body={"entities": []}))

    await gaana._safe_request("POST", endpoints.trending_url, headers={"Cookie": "__ul=Hindi;"})

    headers = session.calls[0]["headers"]
    # No faked browser identity: aiohttp's own User-Agent is sent.
    assert "User-Agent" not in headers and "Origin" not in headers and "Referer" not in headers
    assert headers["Accept"] == "application/json, text/plain, */*"
    assert headers["Cookie"] == "__ul=Hindi;"  # per-call headers are kept


@pytest.mark.asyncio
async def test_unicode_keyword_is_sent_url_encoded_as_a_parameter(gaana):
    session = use(gaana, FakeResponse(body={"gr": [{"gd": []}]}))

    await gaana.search_songs("മലരേ & Simon", 10)

    call = session.calls[0]
    assert call["url"] == endpoints.search_url  # nothing concatenated onto the URL
    assert call["params"]["keyword"] == "മലരേ & Simon"
    assert call["params"]["secType"] == "track"
    sent = str(URL(call["url"]).with_query(call["params"]))
    assert "keyword=%E0%B4%AE%E0%B4%B2%E0%B4%B0%E0%B5%87" in sent
    assert "%26" in sent  # '&' no longer splits the keyword


@pytest.mark.asyncio
async def test_breaker_opens_on_403_and_short_circuits(gaana):
    session = use(gaana, FakeResponse(status=403, raw=b"<HTML>Access Denied</HTML>"))

    with pytest.raises(BlockedError) as first:
        await gaana._safe_request("POST", endpoints.trending_url)
    assert first.value.status == 403
    assert first.value.retry_after == 120

    with pytest.raises(BlockedError) as second:
        await gaana.search_songs("Tum Hi Ho", 10)
    assert second.value.status == 403
    assert 0 < second.value.retry_after <= 120
    assert len(session.calls) == 1  # the second call never reached Gaana


@pytest.mark.parametrize("status", [401, 429])
@pytest.mark.asyncio
async def test_other_refusals_are_blocks_too(gaana, status):
    use(gaana, FakeResponse(status=status, headers={"Retry-After": "300"}))

    with pytest.raises(BlockedError) as blocked:
        await gaana._safe_request("POST", endpoints.trending_url)
    assert blocked.value.status == status
    assert blocked.value.retry_after == 300  # Gaana's Retry-After wins when longer


def test_breaker_doubles_on_repeat_up_to_900_and_resets_on_success():
    now = [0.0]
    breaker = CircuitBreaker(cooldown=120, clock=lambda: now[0])

    assert breaker.trip(403) == 120
    assert breaker.trip(403) == 120  # same block reported by a parallel request
    now[0] += 121
    assert breaker.trip(403) == 240
    for expected in (480, 900, 900):
        now[0] += 1000
        assert breaker.trip(429) == expected
    now[0] += 1000
    breaker.success()
    assert breaker.trip(403) == 120


@pytest.mark.asyncio
async def test_server_errors_and_network_failures_are_unavailable_not_blocked(gaana):
    use(gaana, FakeResponse(status=502))
    with pytest.raises(UpstreamUnavailable):
        await gaana._safe_request("POST", endpoints.trending_url)

    use(gaana, aiohttp.ClientConnectionError("reset"))
    with pytest.raises(UpstreamUnavailable):
        await gaana._safe_request("POST", endpoints.trending_url)

    use(gaana, asyncio.TimeoutError())
    with pytest.raises(UpstreamUnavailable):
        await gaana._safe_request("POST", endpoints.trending_url)

    gaana.breaker.check()  # none of these opened the breaker


@pytest.mark.asyncio
async def test_non_json_body_is_no_results(gaana):
    use(gaana, FakeResponse(raw=b"<html>not json</html>"))

    assert await gaana._safe_request("POST", endpoints.trending_url) == {"error": "Unable to find any results!"}


@pytest.mark.asyncio
async def test_list_responses_are_cached_but_song_details_are_not(gaana):
    session = use(gaana, FakeResponse(body={"entities": [{"seokey": "a"}]}))

    first = await gaana._safe_request("POST", endpoints.trending_url, headers={"Cookie": "__ul=Hindi;"})
    first["entities"].clear()  # callers can't damage the cached copy
    second = await gaana._safe_request("POST", endpoints.trending_url, headers={"Cookie": "__ul=Hindi;"})
    assert second == {"entities": [{"seokey": "a"}]}
    assert len(session.calls) == 1

    await gaana._safe_request("POST", endpoints.trending_url, headers={"Cookie": "__ul=Tamil;"})
    assert len(session.calls) == 2  # another language is another list

    await gaana._safe_request("POST", endpoints.song_details_url + "a", cache=False)
    await gaana._safe_request("POST", endpoints.song_details_url + "a", cache=False)
    assert len(session.calls) == 4


@pytest.mark.asyncio
async def test_no_results_are_not_cached(gaana):
    session = use(gaana, FakeResponse(status=404))

    await gaana._safe_request("POST", endpoints.trending_url)
    await gaana._safe_request("POST", endpoints.trending_url)

    assert len(session.calls) == 2


def test_cache_entries_expire():
    now = [0.0]
    cache = ResponseCache(ttl=600, clock=lambda: now[0])
    key = cache.key("POST", "https://x", {"params": {"keyword": "a"}})
    cache.put(key, {"v": 1})
    assert cache.get(key) == {"v": 1}
    now[0] += 601
    assert cache.get(key) is None


@pytest.mark.asyncio
async def test_request_starts_are_spaced_out(monkeypatch):
    monkeypatch.setenv("GAANA_MIN_INTERVAL_MS", "200")
    now = [100.0]
    slept = []

    async def fake_sleep(seconds):
        slept.append(round(seconds, 3))
        now[0] += seconds

    monkeypatch.setattr("api.upstream.asyncio.sleep", fake_sleep)
    g = GaanaPy()
    await g.aiohttp.close()
    assert g._pacer.interval == 0.2
    g._pacer._clock = lambda: now[0]
    starts = []

    async def stub(method, url, **kwargs):
        starts.append(round(now[0], 3))
        return {}

    g._request_now = stub
    await asyncio.gather(*[g._safe_request("POST", f"https://example.invalid/{i}") for i in range(4)])

    assert starts == [100.0, 100.2, 100.4, 100.6]
    assert slept == [0.2, 0.2, 0.2]


@pytest.mark.asyncio
async def test_requests_waiting_in_the_pacer_do_not_go_out_after_a_block(monkeypatch):
    monkeypatch.setenv("GAANA_MIN_INTERVAL_MS", "200")
    real_sleep = asyncio.sleep
    now = [100.0]
    pacer_sleeps = []
    g = GaanaPy()
    await g.aiohttp.close()
    g._pacer._clock = lambda: now[0]
    g.breaker._clock = lambda: now[0]

    async def fake_sleep(seconds):
        # Wait in the pacer until the first request has been refused by Gaana.
        pacer_sleeps.append(round(seconds, 3))
        now[0] += seconds
        while g.breaker.remaining() == 0:
            await real_sleep(0)

    class SlowRefusal(FakeResponse):
        async def __aenter__(self):
            # Gaana answers only once the other three requests are queued in the pacer.
            while len(pacer_sleeps) < 3:
                await real_sleep(0)
            return self

    monkeypatch.setattr("api.upstream.asyncio.sleep", fake_sleep)
    session = use(g, SlowRefusal(status=403, raw=b"<HTML>Access Denied</HTML>"))

    results = await asyncio.wait_for(asyncio.gather(
        *[g._safe_request("POST", f"https://example.invalid/{i}") for i in range(4)],
        return_exceptions=True,
    ), timeout=5)

    # Only the first request reached Gaana; the three already past the semaphore and
    # sleeping in the pacer were refused by the breaker once their turn came.
    assert pacer_sleeps == [0.2, 0.2, 0.2]  # three requests were queued in the pacer
    assert len(session.calls) == 1
    assert all(isinstance(r, BlockedError) and r.status == 403 for r in results)


@pytest.mark.asyncio
async def test_pacer_without_interval_does_not_wait():
    pacer = Pacer(interval_ms=0)
    started = time.monotonic()
    for _ in range(50):
        await pacer.wait()
    assert time.monotonic() - started < 0.05
