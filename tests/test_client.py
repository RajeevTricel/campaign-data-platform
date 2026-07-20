from datetime import date

import pytest
import responses

from common.config import WindsorSettings
from windsor.client import WindsorClient, WindsorBadRequest

BASE = "https://connectors.windsor.ai"
D = date(2026, 7, 1)


def _client():
    return WindsorClient(WindsorSettings(api_key="test-key", _env_file=None), sleep=lambda s: None)


@responses.activate
def test_get_data_returns_rows():
    responses.get(f"{BASE}/google_ads", json={"data": [{"date": "2026-07-01", "clicks": 10}]})
    rows = _client().get_data("google_ads", fields=["date", "clicks"], date_from=D, date_to=D)
    assert rows == [{"date": "2026-07-01", "clicks": 10}]
    assert "api_key=test-key" in responses.calls[0].request.url


@responses.activate
def test_400_never_retries():
    responses.get(f"{BASE}/google_ads", status=400, body="bad fields")
    with pytest.raises(WindsorBadRequest):
        _client().get_data("google_ads", fields=["nope"], date_from=D, date_to=D)
    assert len(responses.calls) == 1
