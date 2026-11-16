"""GaanaPyClient load controls: back off when Gaana blocks us, share duplicate requests."""

import asyncio

import httpx
import pytest

from app.integrations.errors import ProviderNotFound, ProviderUnavailable
from app.integrations.gaanapy.client import GaanaPyClient


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Upstream:
    """GaanaPy stand-in: answers 502 (Gaana refused) while `blocked`, else 200."""

    def __init__(self):
        self.blocked = False
        self.unreachable = 0  # fail this many requests at the transport level
        self.calls = 0
        self.gate: asyncio.Event | None = None

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.unreachable:
            self.unreachable -= 1
            raise httpx.ConnectError("GaanaPy down")
        if self.gate is not None:
            await self.gate.wait()
        if request.url.params.get("seokey") == "missing":
            return httpx.Response(404, json={"detail": "Unable to find any results!"})
        if self.blocked:
            return httpx.Response(502, json={"error": "Upstream data source error: UpstreamError"})
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
