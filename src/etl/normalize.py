from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

# Windsor field name (from Step 1 discovery)  ->  our clean column name
FIELD_MAP = {
    "date": "date",
    "account_id": "account_id",       # <- confirm vs your discovery notes
    "campaign_id": "campaign_id",     # <- confirm
    "campaign": "campaign_name",      # <- confirm
    "currency": "currency",           # <- confirm (needed later for FX)
    "spend": "spend",
    "impressions": "impressions",
    "clicks": "clicks",
    "conversions": "conversions",
    "conversion_value": "revenue",    # <- confirm
    "campaign_status": "status",      # <- confirm
    "campaign_budget": "budget",      # <- confirm
}
METRICS = ("spend", "impressions", "clicks", "conversions", "revenue", "budget")
KEY = ("platform", "account_id", "campaign_id", "date")


class NormalizationError(ValueError): ...


def _num(v):
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except InvalidOperation as e:
        raise NormalizationError(f"bad number: {v!r}") from e


def normalize_row(raw: dict) -> dict:
    row = {clean: raw.get(win) for win, clean in FIELD_MAP.items()}
    row["platform"] = "google_ads"
    try:
        row["date"] = date.fromisoformat(str(row["date"])[:10])
    except ValueError as e:
        raise NormalizationError(f"bad date: {row['date']!r}") from e
    for m in METRICS:
        row[m] = _num(row.get(m))
    row["loaded_at"] = datetime.now(timezone.utc).isoformat()
    missing = [k for k in KEY if row.get(k) in (None, "")]
    if missing:
        raise NormalizationError(f"row missing key fields {missing}")
    return row
