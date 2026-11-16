import pytest


@pytest.fixture(autouse=True)
def _no_request_pacing(monkeypatch):
    """Tests never talk to Gaana, so don't make them wait out the request spacing.

    Tests of the pacing itself set GAANA_MIN_INTERVAL_MS again.
    """
    monkeypatch.setenv("GAANA_MIN_INTERVAL_MS", "0")
