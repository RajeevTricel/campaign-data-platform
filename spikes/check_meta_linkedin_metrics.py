"""
spikes/check_meta_linkedin_metrics.py

Checks Ajay's Facebook (Meta) and LinkedIn metric lists against what each
connector actually exposes via /{connector}/fields.

Unlike check_ajay_metrics.py (one Google-Ads list run across all connectors),
this uses a SEPARATE candidate list per connector — Facebook ids are checked
only against `facebook`, LinkedIn ids only against `linkedin`. That is the
right shape: each platform has its own vocabulary.

Same project conventions (spikes/list_fields.py, diag.py):
  - key from os.environ["WINDSOR_API_KEY"]
  - one /fields call PER CONNECTOR, matching done in memory (no per-candidate
    data pulls -> cannot hang)
  - filter on the field id; never log the full URL (api_key is a query param)

Run in the Codespace:
    set -a; source .env; set +a
    python spikes/check_meta_linkedin_metrics.py

Entries with an empty candidate list are DERIVED metrics (ratios Ajay marks
"derived directly"); there is no field to look up — they are computed
downstream, not pulled. The script prints them as DERIVE for completeness.
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

import requests

BASE = "https://connectors.windsor.ai"
TIMEOUT = 60

# Per-connector candidate lists, transcribed verbatim from Ajay's doc.
# Where Ajay gave "X or Y", all are listed. [] = derived (no field to check).
PER_CONNECTOR: dict[str, dict[str, list[tuple[str, list[str]]]]] = {
    "facebook": {
        "Core Revenue & Conversion": [
            ("Conversions (Total)",        ["actions", "conversions"]),
            ("Cost / Conversion (CPA)",    ["cost_per_conversion", "cost_per_action_type", "cpa"]),
            ("Conversion Rate (%)",        ["conversion_rate"]),
            ("Conversion Value (Revenue)", ["action_values", "conversion_value"]),
            ("ROAS",                       ["purchase_roas", "website_ctr", "roas"]),
            ("All Conversions",            ["custom_conversions", "actions"]),
        ],
        "Spend & Budget Pacing": [
            ("Cost (Total Spend)",         ["spend"]),
            ("Daily Budget Amount",        ["campaign_daily_budget", "daily_budget"]),
            ("Average CPC",                ["cpc", "cost_per_unique_click"]),
        ],
        "Traffic, Engagement & Click Quality": [
            ("Impressions",                ["impressions"]),
            ("Clicks",                     ["clicks"]),
            ("Click-Through Rate (CTR)",   ["ctr", "unique_ctr"]),
        ],
        "Competitive & Delivery (Meta)": [
            ("Reach (Unique Users)",       ["reach"]),
            ("Frequency",                  ["frequency"]),
            ("Social Impression Share",    ["impressions"]),  # Ajay maps this to impressions
        ],
        "Optimization & Algorithmic Health": [
            ("Target CPA / Bid",           ["optimization_goal", "bid_amount"]),
            ("Actual CPA & Actual ROAS",   []),  # derived: spend/actions, action_values/spend
            ("Cost Per Lead (CPL)",        ["cost_per_lead"]),
            ("Ad Relevance & Diagnostics", ["quality_ranking", "engagement_rate_ranking",
                                            "conversion_rate_ranking"]),
        ],
    },
    "linkedin": {
        "Core Revenue & Conversion": [
            ("Conversions (Total)",        ["conversions", "one_click_conversions"]),
            ("Cost / Conversion (CPA)",    ["cost_per_conversion"]),
            ("Conversion Rate (%)",        ["conversion_rate"]),
            ("Conversion Value (Revenue)", ["conversion_value"]),
            ("ROAS",                       []),  # derived: conversion_value/spend
            ("All Conversions",            ["external_website_conversions"]),
        ],
        "Spend & Budget Pacing": [
            ("Cost (Total Spend)",         ["spend"]),
            ("Daily / Total Budget",       ["daily_budget", "total_budget"]),
            ("Average CPC",                ["cpc", "cost_per_click"]),
        ],
        "Traffic, Engagement & Click Quality": [
            ("Impressions",                ["impressions"]),
            ("Clicks",                     ["clicks"]),
            ("Click-Through Rate (CTR)",   ["ctr"]),
        ],
        "Competitive & Delivery (LinkedIn)": [
            ("Audience Penetration",       ["audience_penetration"]),
            ("Average Dwell Time",         ["average_dwell_time"]),
            ("Viral / Social Impressions", ["viral_impressions"]),
        ],
        "Optimization & Algorithmic Health": [
            ("Target CPA / Bid",           ["unit_cost", "cost_type"]),
            ("Actual CPA & Actual ROAS",   []),  # derived
            ("Cost Per Lead (CPL)",        ["cost_per_lead"]),
            ("Lead Form Completion Rate",  ["lead_group_form_completion_rate"]),
        ],
    },
}


def fetch_field_index(slug: str, key: str) -> dict[str, dict]:
    """One /fields call -> {field_id: {name, type}}. Mirrors WindsorClient.get_fields."""
    r = requests.get(f"{BASE}/{slug}/fields", params={"api_key": key}, timeout=TIMEOUT)
    r.raise_for_status()
    payload = r.json()
    fields = payload if isinstance(payload, list) else (payload.get("fields") or payload.get("data") or [])
    index: dict[str, dict] = {}
    for f in fields:
        if isinstance(f, dict) and "id" in f:
            index[f["id"]] = {"name": f.get("name", ""), "type": f.get("type", "")}
        elif isinstance(f, str):
            index[f] = {"name": "", "type": ""}
    return index


def report_connector(slug: str, sections: dict, available: dict[str, dict]) -> dict[str, int]:
    """Pure: print PRESENT / absent / DERIVE for this connector's own list."""
    print("=" * 82)
    print(f"CONNECTOR: {slug}   ({len(available)} fields exposed by /fields)")
    print("=" * 82)

    tally = {"present": 0, "absent": 0, "derive": 0}
    for section, items in sections.items():
        print(f"\n  ## {section}")
        for label, candidate_ids in items:
            if not candidate_ids:
                print(f"    DERIVE   {label:34s} -> computed downstream (no field to pull)")
                tally["derive"] += 1
                continue
            hit = next((cid for cid in candidate_ids if cid in available), None)
            if hit:
                meta = available[hit]
                extra = f"  [{meta['type']}]" if meta.get("type") else ""
                alt = "" if len(candidate_ids) == 1 else f"   (from {candidate_ids})"
                print(f"    PRESENT  {label:34s} -> id='{hit}'{extra}{alt}")
                tally["present"] += 1
            else:
                print(f"    absent   {label:34s} -> tried {candidate_ids}")
                tally["absent"] += 1

    print(f"\n  SUMMARY [{slug}]: {tally['present']} present, {tally['absent']} absent, "
          f"{tally['derive']} derived")
    return tally


def probe_values(slug: str, available: dict[str, dict], key: str) -> None:
    """OPTIONAL single small pull to confirm the basic metrics return rows."""
    base = [f for f in ("spend", "impressions", "clicks", "conversions") if f in available]
    if not base:
        print(f"    (no basic metric fields present on {slug}; skipping value probe)")
        return
    today = date.today()
    params = {"api_key": key, "fields": ",".join(base),
              "date_from": (today - timedelta(days=30)).isoformat(), "date_to": today.isoformat()}
    r = requests.get(f"{BASE}/{slug}", params=params, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    rows = data.get("data", []) if isinstance(data, dict) else []
    print(f"    value probe [{slug}]: {len(rows)} rows in last 30d for {base}")


def main() -> int:
    key = os.environ.get("WINDSOR_API_KEY")
    if not key:
        print("ERROR: WINDSOR_API_KEY not set. Run:  set -a; source .env; set +a", file=sys.stderr)
        return 2

    do_probe = "--probe-values" in sys.argv
    for slug, sections in PER_CONNECTOR.items():
        try:
            available = fetch_field_index(slug, key)
        except requests.HTTPError as exc:
            print(f"\n!! {slug}: /fields returned HTTP {exc.response.status_code} "
                  f"— connector not enabled or wrong slug; skipping\n")
            continue
        except Exception as exc:  # noqa: BLE001
            print(f"\n!! {slug}: {type(exc).__name__} — skipping\n")
            continue

        report_connector(slug, sections, available)
        if do_probe:
            try:
                probe_values(slug, available, key)
            except Exception as exc:  # noqa: BLE001
                print(f"    value probe [{slug}] failed: {type(exc).__name__}")

    print("\n" + "=" * 82)
    print("Note: 'present' = the id exists on that connector's /fields. It does NOT mean the")
    print("field is campaign-grain, populated, or the right metric — confirm scale/grain when wiring.")
    print("'absent' = not under the id(s) tried; a different id may exist (targeted follow-up).")
    print("=" * 82)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
