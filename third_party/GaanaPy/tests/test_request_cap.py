"""Local fix: GaanaPy never has more than GAANA_MAX_CONCURRENT requests to Gaana in flight.

Offline test (no Gaana traffic): the real request is replaced by a stub.
"""

import asyncio

from api.gaanapy import GaanaPy


def test_requests_to_gaana_are_capped(monkeypatch):
    monkeypatch.setenv("GAANA_MAX_CONCURRENT", "3")

    async def run() -> int:
        g = GaanaPy()
        active = peak = 0

        async def stub(method, url, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return {}

        g._request_now = stub
        try:
            await asyncio.gather(*[g._safe_request("POST", "https://example.invalid") for _ in range(21)])
        finally:
            await g.aiohttp.close()
        return peak

    assert asyncio.run(run()) == 3
