"""
spikes/probe_metric_values.py

Goes beyond "does the field exist in /fields" (check_*_metrics.py) and asks:
when we actually pull data, do the PRESENT fields return real values, or do they
come back empty?

Why grain-grouped pulls (not one big pull):
  Some present Google Ads fields are keyword/ad level (quality score, expected
  CTR, ad relevance), not campaign level. Requesting them alongside campaign
  metrics makes Windsor either null them out or fan rows to keyword grain (a
  silent row explosion that corrupts population counts). So each connector's
  fields are pulled in grain-consistent GROUPS, and every group reports its row
  count vs distinct campaign keys so fan-out is visible.

Grounded in project facts:
  - metrics pulls only return rows for campaigns that DELIVERED in the window,
    so a 0% field may just mean "no campaign used it" (e.g. target_cpa is only
    set on tCPA strategies) rather than "the field is broken."
  - Windsor caps a response near 100k characters; keep the window modest.
  - key from os.environ["WINDSOR_API_KEY"]; never log the full URL.

Run in the Codespace:
    set -a; source .env; set +a
    python spikes/probe_metric_values.py                 # last 30 days
    python spikes/probe_metric_values.py --days 90        # wider window
    python spikes/probe_metric_values.py --slug google_ads  # one connector
"""
from __future__ import annotations

import os
import sys
import time
from datetime import date, timedelta

import requests

BASE = "https://connectors.windsor.ai"
TIMEOUT = 90
ANCHORS = ["date", "account_id", "campaign_id"]

# Only PRESENT fields (from the discovery results) — pulling an absent field
# would 400 the whole request. Grouped so each group is one grain.
FIELD_GROUPS: dict[str, list[dict]] = {
    "google_ads": [
        {"group": "core campaign metrics", "grain": "campaign", "fields": [
            "campaign_status", "spend", "impressions", "clicks", "conversions",
            "conversion_value", "all_conversions", "cost_per_conversion",
            "conversion_rate", "roas", "cpc", "ctr", "campaign_budget"]},
        {"group": "impression share (search only)", "grain": "campaign", "fields": [
            "search_impression_share", "search_budget_lost_impression_share",
            "search_rank_lost_impression_share", "search_top_impression_share",
            "search_budget_lost_top_impression_share",
            "search_rank_lost_top_impression_share",
            "search_exact_match_impression_share"]},
        {"group": "bid strategy (attributes)", "grain": "campaign", "fields": [
            "target_cpa", "target_roas", "bidding_strategy_type", "bidding_strategy_status"]},
        {"group": "quality (KEYWORD/AD level — expect fan-out or nulls)", "grain": "keyword", "fields": [
            "historical_quality_score", "search_predicted_ctr", "creative_quality_score"]},
    ],
    "facebook": [
        {"group": "core campaign metrics", "grain": "campaign", "fields": [
            "spend", "campaign_daily_budget", "cpc", "impressions", "clicks", "ctr"]},
        {"group": "delivery", "grain": "campaign", "fields": ["reach", "frequency"]},
        {"group": "diagnostics (TEXT, ad level — expect fan-out or nulls)", "grain": "ad", "fields": [
            "quality_ranking"]},
    ],
}


def pull(slug: str, fields: list[str], date_from: date, date_to: date) -> list[dict]:
    req = ANCHORS + [f for f in fields if f not in ANCHORS]
    params = {"api_key": key_from_env(), "fields": ",".join(req),
              "date_from": date_from.isoformat(), "date_to": date_to.isoformat()}
    r = requests.get(f"{BASE}/{slug}", params=params, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    return data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])


def key_from_env() -> str:
    k = os.environ.get("WINDSOR_API_KEY")
    if not k:
        print("ERROR: WINDSOR_API_KEY not set. Run:  set -a; source .env; set +a", file=sys.stderr)
        raise SystemExit(2)
    return k


def _nonempty(v) -> bool:
    return v not in (None, "") and not (isinstance(v, str) and v.strip() == "")


def summarize_group(slug: str, group: dict, rows: list[dict]) -> None:
    """Pure: print row count, grain check, and per-field population for one group."""
    fields = group["fields"]
    print(f"\n  ## {group['group']}  (declared grain: {group['grain']})")
    n = len(rows)
    if n == 0:
        print("    0 rows returned in this window — nothing delivered, or fields not queryable here.")
        return

    distinct_keys = {(r.get("account_id"), r.get("campaign_id"), r.get("date")) for r in rows}
    fanout = "" if n == len(distinct_keys) else \
        f"  <- ROW FAN-OUT: {n} rows vs {len(distinct_keys)} campaign-days (sub-campaign grain!)"
    print(f"    rows: {n}   distinct (account,campaign,date): {len(distinct_keys)}{fanout}")

    width = max(len(f) for f in fields)
    for f in fields:
        populated = sum(1 for r in rows if _nonempty(r.get(f)))
        pct = 100.0 * populated / n
        sample = next((str(r.get(f)) for r in rows if _nonempty(r.get(f))), "")
        sample = (sample[:32] + "…") if len(sample) > 33 else sample
        flag = "  <-- EXISTS BUT ALWAYS EMPTY" if populated == 0 else ""
        print(f"    {f:{width}s}  {populated:>5}/{n} ({pct:5.1f}%)  e.g. {sample!r}{flag}")


def main() -> int:
    key_from_env()  # fail fast if missing
    days = 30
    only = None
    for i, a in enumerate(sys.argv):
        if a == "--days" and i + 1 < len(sys.argv):
            days = int(sys.argv[i + 1])
        if a == "--slug" and i + 1 < len(sys.argv):
            only = sys.argv[i + 1]

    today = date.today()
    dfrom, dto = today - timedelta(days=days), today

    for slug, groups in FIELD_GROUPS.items():
        if only and slug != only:
            continue
        print("=" * 84)
        print(f"CONNECTOR: {slug}   window: {dfrom} .. {dto} ({days}d)")
        print("=" * 84)
        for group in groups:
            try:
                rows = pull(slug, group["fields"], dfrom, dto)
                summarize_group(slug, group, rows)
            except requests.HTTPError as exc:
                print(f"\n  ## {group['group']}: HTTP {exc.response.status_code} "
                      f"— these fields may not be queryable together at this grain; skipping")
            except Exception as exc:  # noqa: BLE001
                print(f"\n  ## {group['group']}: {type(exc).__name__} — skipping")
            time.sleep(0.5)  # polite spacing; well under the 30 req/min ceiling

    print("\n" + "=" * 84)
    print("Reading this:")
    print("  * X/N (%)  = rows where the field was non-null in the window.")
    print("  * 'EXISTS BUT ALWAYS EMPTY' = field is real but unpopulated here — could be")
    print("    sparse by design (e.g. target_cpa only on tCPA campaigns) OR wrong grain.")
    print("  * 'ROW FAN-OUT' = the pull dropped below campaign grain; those numbers are")
    print("    keyword/ad-level rows, so don't treat their metric sums as campaign totals.")
    print("  * 0 rows for a whole connector/group = nothing delivered in the window; widen --days.")
    print("=" * 84)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
