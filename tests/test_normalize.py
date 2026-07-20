from decimal import Decimal
from datetime import date

import pytest

from etl.normalize import normalize_row, NormalizationError


def raw(**o):
    base = {"date": "2026-07-01", "account_id": "123", "campaign_id": "c1",
            "campaign": "Brand", "currency": "EUR", "spend": "12.50", "clicks": "40"}
    base.update(o)
    return base


def test_happy_path():
    r = normalize_row(raw())
    assert r["platform"] == "google_ads"
    assert r["date"] == date(2026, 7, 1)
    assert r["spend"] == Decimal("12.50")
    assert r["currency"] == "EUR"


def test_empty_metric_is_none_not_zero():
    assert normalize_row(raw(spend=""))["spend"] is None


def test_missing_key_raises():
    with pytest.raises(NormalizationError):
        normalize_row(raw(campaign_id=None))
