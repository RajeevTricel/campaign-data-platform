"""
spikes/check_ajay_metrics.py

Checks every field id from Ajay's "Performance Marketing Data Architecture" doc
against what each Windsor connector actually exposes via /{connector}/fields.

Follows the project's discovery conventions (see spikes/list_fields.py, diag.py):
  - reads the key from the environment: os.environ["WINDSOR_API_KEY"]
  - one /fields call PER CONNECTOR, then all matching is done in memory
    (NO per-candidate data pulls -> cannot hang, unlike the first attempt)
  - filters on the field *id*, not the description
  - never logs the full URL (the api_key is a query param)

Run in the Codespace:
    set -a; source .env; set +a          # loads WINDSOR_API_KEY
    python spikes/check_ajay_metrics.py

Optional: also confirm the PRESENT base metrics actually return non-null values
(one small data pull per connector, last 30 days):
    python spikes/check_ajay_metrics.py --probe-values
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

import requests

BASE = "https://connectors.windsor.ai"
TIMEOUT = 60

# Connectors currently confirmed in the project. Microsoft/Bing slug is still
# unconfirmed (see 22-Jul bridge) -> add it here once known.
SLUGS = ["google_ads", "facebook", "linkedin"]

# ---------------------------------------------------------------------------
# Ajay's candidate field ids, grouped exactly as his doc groups them.
# Where Ajay gave alternatives ("X or Y") BOTH are listed so the script can
# tell you which one Windsor actually uses. Nothing here is assumed correct —
# that is the whole point of running this.
# ---------------------------------------------------------------------------
CANDIDATES: dict[str, list[tuple[str, list[str]]]] = {
    "Core Revenue & Conversion": [
        ("Conversions (Total)",            ["conversions"]),
        ("Cost / Conversion (CPA)",        ["cost_per_conversion", "cpa"]),
        ("Conversion Rate (%)",            ["conversion_rate"]),
        ("Conversion Value (Revenue)",     ["conversion_value"]),
        ("ROAS",                           ["roas"]),
        ("All Conversions",                ["all_conversions"]),
    ],
    "Spend & Budget Pacing": [
        ("Cost (Total Spend)",             ["spend", "cost"]),
        ("Daily Budget Amount",            ["campaign_daily_budget", "budget", "campaign_budget"]),
        ("Average CPC",                    ["cpc", "average_cpc"]),
    ],
    "Traffic, Engagement & Click Quality": [
        ("Impressions",                    ["impressions"]),
        ("Clicks",                         ["clicks"]),
        ("Click-Through Rate (CTR)",       ["ctr"]),
    ],
    "Competitive Auction & Impression Share": [
        ("Search Impression Share",        ["search_impression_share"]),
        ("Search Lost IS (Budget)",        ["search_budget_lost_impression_share"]),
        ("Search Lost IS (Rank)",          ["search_rank_lost_impression_share"]),
        ("Search Top Impression Share",    ["search_top_impression_share"]),
        ("Search Lost Top IS (Budget)",    ["search_budget_lost_top_impression_share"]),
        ("Search Lost Top IS (Rank)",      ["search_rank_lost_top_impression_share"]),
        ("Exact Match Impression Share",   ["search_exact_match_impression_share"]),
        ("Click Share",                    ["click_share"]),
    ],
    "Bid Strategy Target & Algorithmic Health": [
        ("Target CPA",                     ["target_cpa"]),
        ("Target ROAS",                    ["target_roas"]),
        ("Bid Strategy Type",              ["bidding_strategy_type"]),
        ("Bid Strategy Status",            ["bidding_strategy_status"]),
        ("Quality Score",                  ["historical_quality_score", "quality_score"]),
        ("Expected CTR",                   ["search_predicted_ctr"]),
        ("Ad Relevance",                   ["creative_quality_score", "ad_relevance"]),
        ("Cost Per Lead (CPL)",            ["cost_per_lead"]),
    ],
}

# Base fields already CONFIRMED in the pipeline (live 152-row Google Ads pull).
# Printed for reference so you can see the "already have it" set at a glance.
CONFIRMED_BASE = [
    "date", "account_id", "campaign_id", "campaign",
    "currency", "spend", "impressions", "clicks",
    "conversions", "conversion_value", "campaign_status", "campaign_budget",
]


def fetch_field_index(slug: str, key: str) -> dict[str, dict]:
    """One /fields call. Returns {field_id: {name, type}} for the connector.

    Mirrors WindsorClient.get_fields: the payload may be a bare list or a dict
    wrapping the list under 'fields' or 'data'.
    """
    r = requests.get(f"{BASE}/{slug}/fields", params={"api_key": key}, timeout=TIMEOUT)
    r.raise_for_status()
    payload = r.json()
    fields = payload if isinstance(payload, list) else (payload.get("fields") or payload.get("data") or [])
    index: dict[str, dict] = {}
    for f in fields:
        if isinstance(f, dict) and "id" in f:
            index[f["id"]] = {"name": f.get("name", ""), "type": f.get("type", "")}
        elif isinstance(f, str):  # some connectors return a plain list of ids
            index[f] = {"name": "", "type": ""}
    return index


def report_connector(slug: str, available: dict[str, dict]) -> dict[str, int]:
    """Pure: given the available field index, print PRESENT/absent for Ajay's list.

    No network here — this is what makes the script testable offline.
    """
    print("=" * 78)
    print(f"CONNECTOR: {slug}   ({len(available)} fields exposed by /fields)")
    print("=" * 78)

    tally = {"present": 0, "absent": 0}
    for section, items in CANDIDATES.items():
        print(f"\n  ## {section}")
        for label, candidate_ids in items:
            hit = next((cid for cid in candidate_ids if cid in available), None)
            if hit:
                meta = available[hit]
                extra = f"  [{meta['type']}]" if meta.get("type") else ""
                alt = "" if len(candidate_ids) == 1 else f"   (from {candidate_ids})"
                print(f"    PRESENT  {label:32s} -> id='{hit}'{extra}{alt}")
                tally["present"] += 1
            else:
                print(f"    absent   {label:32s} -> tried {candidate_ids}")
                tally["absent"] += 1

    print(f"\n  SUMMARY [{slug}]: {tally['present']} present, {tally['absent']} absent "
          f"(of {tally['present'] + tally['absent']} of Ajay's metrics)")
    return tally


def probe_values(slug: str, available: dict[str, dict], key: str) -> None:
    """OPTIONAL single small pull: confirm the PRESENT base metrics are non-null.

    One data call per connector, last 30 days, only the confirmed-present base
    fields. Still no per-candidate looping.
    """
    base_present = [f for f in CONFIRMED_BASE if f in available]
    if not base_present:
        print(f"    (no base fields present on {slug}; skipping value probe)")
        return
    today = date.today()
    params = {
        "api_key": key,
        "fields": ",".join(base_present),
        "date_from": (today - timedelta(days=30)).isoformat(),
        "date_to": today.isoformat(),
    }
    r = requests.get(f"{BASE}/{slug}", params=params, timeout=TIMEOUT)
    r.raise_for_status()
    rows = r.json().get("data", []) if isinstance(r.json(), dict) else []
    print(f"    value probe [{slug}]: {len(rows)} rows in last 30d for base fields "
          f"{base_present}")
    if rows:
        sample = rows[0]
        nonnull = [k for k in base_present if sample.get(k) not in (None, "")]
        print(f"      first row non-null base fields: {nonnull}")


def main() -> int:
    key = os.environ.get("WINDSOR_API_KEY")
    if not key:
        print("ERROR: WINDSOR_API_KEY not set. Run:  set -a; source .env; set +a", file=sys.stderr)
        return 2

    do_probe = "--probe-values" in sys.argv
    grand = {"present": 0, "absent": 0}

    for slug in SLUGS:
        try:
            available = fetch_field_index(slug, key)
        except requests.HTTPError as exc:
            print(f"\n!! {slug}: /fields returned HTTP {exc.response.status_code} "
                  f"— connector not enabled or wrong slug; skipping\n")
            continue
        except Exception as exc:  # noqa: BLE001 - discovery script, keep going
            print(f"\n!! {slug}: {type(exc).__name__} — skipping\n")
            continue

        tally = report_connector(slug, available)
        grand["present"] += tally["present"]
        grand["absent"] += tally["absent"]

        if do_probe:
            try:
                probe_values(slug, available, key)
            except Exception as exc:  # noqa: BLE001
                print(f"    value probe [{slug}] failed: {type(exc).__name__}")

    print("\n" + "=" * 78)
    print(f"GRAND TOTAL across {len(SLUGS)} connectors: "
          f"{grand['present']} present / {grand['absent']} absent")
    print("Note: 'present' means the field id exists on that connector's /fields.")
    print("It does NOT mean the field is campaign-grain, populated, or the same")
    print("metric on every platform — read the accompanying assessment doc.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
