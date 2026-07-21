"""Raw Windsor row -> clean, typed row with a stable column set, for any connector."""
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from etl.connectors import GOOGLE_ADS, ConnectorSpec

METRICS = ("spend", "impressions", "clicks", "conversions", "revenue", "budget")

# Only date is required across every connector right now, since Facebook/LinkedIn's
# account_id and campaign_id fields aren't confirmed yet (see connectors.py TODOs).
# Once those are confirmed, extend this to ("platform", "account_id", "campaign_id", "date").
KEY = ("platform", "date")

CLEAN_COLUMNS = (
    "platform", "account_id", "campaign_id", "campaign_name", "date", "currency", "status",
    "spend", "impressions", "clicks", "conversions", "revenue", "budget", "loaded_at",
)

# Back-compat: run_pull.py / older callers import FIELD_MAP directly.
FIELD_MAP = GOOGLE_ADS.field_map


class NormalizationError(ValueError):
    ...


def _num(v):
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except InvalidOperation as e:
        raise NormalizationError(f"bad number: {v!r}") from e


def normalize_row(raw: dict, spec: ConnectorSpec = GOOGLE_ADS) -> dict:
    row = {c: None for c in CLEAN_COLUMNS}          # identical column set for every connector
    for windsor_field, clean in spec.field_map.items():
        row[clean] = raw.get(windsor_field)
    row["platform"] = spec.key
    try:
        row["date"] = date.fromisoformat(str(row["date"])[:10])
    except ValueError as e:
        raise NormalizationError(f"{spec.key}: bad date {row.get('date')!r}") from e
    for m in METRICS:
        row[m] = _num(row.get(m))
    row["loaded_at"] = datetime.now(timezone.utc).isoformat()
    missing = [k for k in KEY if row.get(k) in (None, "")]
    if missing:
        raise NormalizationError(f"{spec.key}: row missing key fields {missing}")
    return row
