"""Per-connector specs: slug, sheet label, field map, and date-window behavior.

Adding a connector = adding a new ConnectorSpec entry here. Nothing in
normalize.py, sampling.py, or export_excel.py needs to change.
"""
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ConnectorSpec:
    key: str                       # canonical platform key -> the "platform" column value
    windsor_slug: str               # the /{slug} path segment on the Windsor API
    label: str                      # sheet name in the Excel
    field_map: dict                 # windsor field name -> clean column name (campaign level)
    lookback_days: int = 7          # how many days back from date_to to pull
    fixed_date_to: date | None = None  # if set, use this instead of "today" (stale connectors)


GOOGLE_ADS = ConnectorSpec(
    key="google_ads",
    windsor_slug="google_ads",
    label="Google Ads",
    field_map={
        "date": "date",
        "account_id": "account_id",
        "campaign_id": "campaign_id",
        "campaign": "campaign_name",
        "currency": "currency",
        "spend": "spend",
        "impressions": "impressions",
        "clicks": "clicks",
        "conversions": "conversions",
        "conversion_value": "revenue",
        "campaign_status": "status",
        "campaign_budget": "budget",
    },
)

META = ConnectorSpec(
    key="meta",
    windsor_slug="facebook",           # confirmed: "facebook", not "meta" or "facebook_ads"
    label="Facebook Ads",
    field_map={
        "date": "date",
        "campaign": "campaign_name",
        "spend": "spend",
        "clicks": "clicks",
        "account_id": "account_id",     # confirmed: same name as Google Ads
        "campaign_id": "campaign_id",   # confirmed: same name as Google Ads
        # not yet confirmed for Facebook — add once checked:
        # "impressions": "impressions",
        # "conversions": "conversions",
        # "revenue": "revenue",
        # "status": "status",
        # "budget": "budget",
        # "currency": "currency",
    },
)

LINKEDIN = ConnectorSpec(
    key="linkedin",
    windsor_slug="linkedin",           # confirmed
    label="LinkedIn Ads",
    fixed_date_to=date(2025, 11, 4),   # last confirmed activity (442 rows found, 2023-01-01..today)
    lookback_days=7,                   # -> pulls 2025-10-28 .. 2025-11-04
    field_map={
        "date": "date",
        "campaign": "campaign_name",
        "spend": "spend",
        "clicks": "clicks",
        "account_id": "account_id",     # confirmed: same name as Google Ads
        "campaign_id": "campaign_id",   # confirmed: same name as Google Ads
        # not yet confirmed for LinkedIn — add once checked:
        # "impressions": "impressions",
        # "conversions": "conversions",
        # "revenue": "revenue",
        # "status": "status",
        # "budget": "budget",
        # "currency": "currency",
    },
)

REGISTRY = {s.key: s for s in (GOOGLE_ADS, META, LINKEDIN)}
