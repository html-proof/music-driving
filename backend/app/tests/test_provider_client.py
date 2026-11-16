"""GaanaPyClient load controls: back off when Gaana blocks us, share duplicate requests."""

import asyncio

import httpx
import pytest

from app.integrations.errors import ProviderError, ProviderInvalidRequest, ProviderNotFound, ProviderUnavailable
from app.integrations.gaanapy.client import GaanaPyClient


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Upstream:
    """GaanaPy stand-in: answers 503 "blocked" while `blocked`, `status` when set, else 200."""

    def __init__(self):
        self.blocked = False
        self.retry_after = 30
        self.status: int | None = None  # e.g. 502 (Gaana network error) or 500 (GaanaPy bug)
        self.unreachable = 0  # fail this many requests at the transport level
        self.read_timeouts = 0  # GaanaPy took the request but answered too late
        self.calls = 0
        self.params: list[dict] = []
        self.gate: asyncio.Event | None = None

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        self.params.append(dict(request.url.params))
        if self.unreachable:
            self.unreachable -= 1
            raise httpx.ConnectError("GaanaPy down")
        if self.read_timeouts:
            self.read_timeouts -= 1
            raise httpx.ReadTimeout("GaanaPy slow")
        if self.gate is not None:
            await self.gate.wait()
        if request.url.params.get("seokey") == "missing":
            return httpx.Response(404, json={"detail": "Unable to find any results!"})
        if request.url.params.get("seokey") == "Bad Key":
            return httpx.Response(422, json={"detail": "invalid seokey"})
        if self.blocked:
            return httpx.Response(503, json={"error": "blocked", "upstream_status": 403,
                                             "retry_after": self.retry_after})
        if self.status == 502:
            return httpx.Response(502, json={"error": "upstream_unavailable", "detail": "ClientConnectorError"})
        if self.status == 500:
            return httpx.Response(500, json={"error": "internal", "detail": "KeyError"})
        return httpx.Response(200, json=[{"seokey": request.url.params.get("seokey", "x")}])


@pytest.fixture
def upstream() -> Upstream:
    return Upstream()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
async def client(upstream, clock):
    c = GaanaPyClient("http://gaanapy.test", retries=2, transport=httpx.MockTransport(upstream.handler),
                      block_cooldown_seconds=60, block_cooldown_max_seconds=300, clock=clock)
    yield c
    await c.close()


async def test_a_block_is_not_retried_and_starts_a_cooldown(client, upstream, clock):
    upstream.blocked = True
    with pytest.raises(ProviderUnavailable):
        await client.song_info("a")
    assert upstream.calls == 1  # no retries against a block
    assert client.blocked

    # During the cooldown nothing reaches GaanaPy / Gaana.
    for song in ("a", "b", "c"):
        with pytest.raises(ProviderUnavailable):
            await client.song_info(song)
    assert upstream.calls == 1


async def test_cooldown_doubles_while_blocked_and_ends_when_gaana_answers(client, upstream, clock):
    upstream.blocked = True
    with pytest.raises(ProviderUnavailable):
        await client.song_info("a")
    clock.now += 61  # first cooldown (60 s) over: one probe goes out and is refused
    with pytest.raises(ProviderUnavailable):
        await client.song_info("a")
    assert upstream.calls == 2
    clock.now += 61  # still inside the doubled 120 s cooldown
    with pytest.raises(ProviderUnavailable):
        await client.song_info("a")
    assert upstream.calls == 2

    upstream.blocked = False
    clock.now += 60  # 121 s after the probe: next probe succeeds and ends the cooldown
    assert await client.song_info("a") == [{"seokey": "a"}]
    assert not client.blocked
    assert await client.song_info("b") == [{"seokey": "b"}]
    assert upstream.calls == 4


async def test_cooldown_is_capped(client, upstream, clock):
    upstream.blocked = True
    for _ in range(6):
        with pytest.raises(ProviderUnavailable):
            await client.song_info("a")
        clock.now += 301  # beyond the 300 s maximum each time, so every probe goes out
    assert upstream.calls == 6
    assert client._cooldown == 300


async def test_only_one_probe_at_a_time_after_a_cooldown(client, upstream, clock):
    upstream.blocked = True
    with pytest.raises(ProviderUnavailable):
        await client.song_info("a")
    clock.now += 61
    upstream.blocked = False
    upstream.gate = asyncio.Event()
    probe = asyncio.create_task(client.song_info("a"))
    await asyncio.sleep(0)
    with pytest.raises(ProviderUnavailable):  # a different request while the probe is out
        await client.song_info("b")
    upstream.gate.set()
    assert await probe == [{"seokey": "a"}]
    assert upstream.calls == 2


async def test_parallel_refusals_count_as_one_block(client, upstream, clock):
    # Home / search send many requests at once; one block episode answers all of them
    # with 503. That is one block: the cooldown must not double once per answer.
    upstream.blocked = True
    upstream.retry_after = 30
    upstream.gate = asyncio.Event()
    tasks = [asyncio.create_task(client.trending(lang, 12)) for lang in ("hindi", "tamil", "telugu", "malayalam",
                                                                         "kannada", "english")]
    tasks.append(asyncio.create_task(client.charts(50)))
    await asyncio.sleep(0)
    upstream.gate.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert all(isinstance(r, ProviderUnavailable) for r in results)
    assert upstream.calls == 7
    assert client._cooldown == 60  # the base cooldown, not 60 -> 120 -> ... -> 300
    clock.now += 59
    assert client.blocked
    clock.now += 2
    assert not client.blocked  # free again after the base cooldown

    # The next real refusal (the probe) is a repeat block and doubles it.
    upstream.gate = None
    with pytest.raises(ProviderUnavailable):
        await client.song_info("a")
    assert client._cooldown == 120


async def test_parallel_refusal_asking_for_longer_extends_the_cooldown(clock):
    gate = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        await gate.wait()
        wait = 200 if request.url.params["seokey"] == "b" else 30  # GaanaPy's breaker asks b for longer
        return httpx.Response(503, json={"error": "blocked", "upstream_status": 403, "retry_after": wait})

    c = GaanaPyClient("http://gaanapy.test", transport=httpx.MockTransport(handler),
                      block_cooldown_seconds=60, block_cooldown_max_seconds=300, clock=clock)
    try:
        tasks = [asyncio.create_task(c.song_info(k)) for k in ("a", "b")]
        await asyncio.sleep(0)
        gate.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        assert c._cooldown == 60  # not doubled
        clock.now += 199
        assert c.blocked  # but the longest retry_after is honoured
        clock.now += 2
        assert not c.blocked
    finally:
        await c.close()


async def test_late_success_from_before_a_block_does_not_end_it(client, upstream, clock):
    upstream.gate = asyncio.Event()
    slow = asyncio.create_task(client.song_info("slow"))  # sent while Gaana still answered
    await asyncio.sleep(0)
    upstream.gate.set()
    upstream.gate = None
    upstream.blocked = True
    with pytest.raises(ProviderUnavailable):
        await client.song_info("a")
    assert client.blocked
    upstream.blocked = False
    await slow  # answered 200, but it was sent before the block began
    assert client.blocked


async def test_identical_requests_in_flight_share_one_call(client, upstream):
    upstream.gate = asyncio.Event()
    tasks = [asyncio.create_task(client.song_info("same")) for _ in range(5)]
    other = asyncio.create_task(client.song_info("other"))
    await asyncio.sleep(0)
    upstream.gate.set()
    results = await asyncio.gather(*tasks, other)
    assert all(r == [{"seokey": "same"}] for r in results[:5])
    assert upstream.calls == 2  # one for "same", one for "other"


async def test_gaanapy_unreachable_is_retried_without_a_cooldown(client, upstream):
    upstream.unreachable = 2  # the local GaanaPy service hiccups twice, then answers
    assert await client.song_info("a") == [{"seokey": "a"}]
    assert upstream.calls == 3
    assert not client.blocked


async def test_not_found_does_not_start_a_cooldown(client, upstream):
    with pytest.raises(ProviderNotFound):
        await client.song_info("missing")
    assert not client.blocked


async def test_retry_after_longer_than_the_cooldown_is_honoured(client, upstream, clock):
    upstream.blocked = True
    upstream.retry_after = 200  # GaanaPy's own breaker asks for longer than our 60 s
    with pytest.raises(ProviderUnavailable):
        await client.song_info("a")
    clock.now += 61
    with pytest.raises(ProviderUnavailable):
        await client.song_info("a")
    assert upstream.calls == 1  # still waiting out GaanaPy's retry_after
    clock.now += 140
    upstream.blocked = False
    assert await client.song_info("a") == [{"seokey": "a"}]
    assert upstream.calls == 2


async def test_upstream_unavailable_fails_the_call_without_a_cooldown(client, upstream):
    upstream.status = 502  # Gaana timed out / 5xx: not a block
    with pytest.raises(ProviderUnavailable):
        await client.song_info("a")
    assert not client.blocked
    assert upstream.calls == 1  # not retried
    upstream.status = None
    assert await client.song_info("b") == [{"seokey": "b"}]


async def test_gaanapy_internal_error_is_a_provider_error_without_a_cooldown(client, upstream):
    upstream.status = 500
    with pytest.raises(ProviderError) as info:
        await client.song_info("a")
    assert not isinstance(info.value, (ProviderUnavailable, ProviderNotFound))
    assert not client.blocked
    assert upstream.calls == 1


async def test_invalid_request_is_its_own_not_found(client, upstream):
    with pytest.raises(ProviderInvalidRequest):
        await client.song_info("Bad Key")
    assert issubclass(ProviderInvalidRequest, ProviderNotFound)
    assert not client.blocked


async def test_read_timeout_is_not_retried(client, upstream):
    upstream.read_timeouts = 1  # GaanaPy already has the request: a retry would repeat its Gaana calls
    with pytest.raises(ProviderUnavailable):
        await client.song_info("a")
    assert upstream.calls == 1
    assert not client.blocked


async def test_search_sends_the_page(client, upstream):
    await client.search_songs("മലരേ & co", 5, 3)
    assert upstream.params[-1] == {"query": "മലരേ & co", "limit": "5", "page": "3"}
