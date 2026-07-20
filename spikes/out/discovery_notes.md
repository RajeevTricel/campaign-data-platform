# Windsor discovery notes — Google Ads (sandbox)

> Fill these in from Step 1 (`spikes/peek.py`). The **exact Windsor field names** go on the
> left of `FIELD_MAP` in `src/etl/normalize.py`. This file is the input to the Step 3 mapping
> and, later, the Wave-2 field maps and the R1 budget-entity evidence (plan Task 0.4).

Confirmed connector slug: `________`  (plan candidates: google_ads, googleads)
Sandbox account id used: `________`
Date range peeked: `________`

## FR1 standard field set — exact Windsor names

| Concept | Windsor field name (confirm) | Notes |
|---|---|---|
| date | | |
| account id | | |
| account name | | |
| campaign id | | |
| campaign name | | |
| spend | | |
| impressions | | |
| clicks | | |
| conversions | | |
| revenue / conversion value | | |
| status | | campaign_status? |
| budget | | where does the budget live — campaign, shared budget? (R1) |
| **currency (account)** | | **finding F2 — required for later FX; must be captured at landing** |

## Observations
- Pagination / row-limit behaviour on a wide date range: `________`
- Any account-filter param (needed later for per-client backfill): `________`
- Anything surprising (nesting, nulls-as-strings, "0" vs ""): `________`
