#!/usr/bin/env python3
"""
probe_linkedin_reality.py  (v2 — field-isolating)
=================================================
LinkedIn Ads *reality* probe. Goes beyond "does the field exist in /fields" to
"does the field actually return data when pulled" — and, because LinkedIn's API
refuses some field combinations, it probes fields ONE AT A TIME instead of all at
once (v1 asked for ~15 fields together and Windsor 500'd the whole request).

Covers in one run against the `linkedin` connector:
  TASK 1  Population probe — per field: is it pullable at all, and if so what %
          of rows carry a non-empty value. "Present in catalogue but errors on
          pull" is reported as its own category (it is NOT usable data).
  TASK 2  Status values — the distinct campaign-status values (LinkedIn's
          ENABLED / PAUSED / REMOVED equivalent).
  TASK 3  (LinkedIn slice) campaign_start_date / campaign_end_date reality.

KEY BEHAVIOUR — WHY FIELD-BY-FIELD + a "no-date" retry:
  * Vanilla time-series metrics (spend/impressions/clicks/…) pull fine WITH the
    daily `date` segment.
  * Campaign ENTITY attributes (status, start/end date) often CANNOT be segmented
    by date — requesting them alongside `date` makes LinkedIn error. So when a
    field fails WITH `date`, this probe retries it WITHOUT `date` (campaign grain).
    A field that only succeeds without `date` is a per-campaign attribute — exactly
    what status / start / end date are.

WHY A ONE-YEAR WINDOW: Tricel's LinkedIn campaigns went quiet after 2025-11-04.
A 30/90-day window from today returns ZERO rows. Default --days 365 reaches back
across the quiet date into the active period. Widen if a run is still empty.

SECURITY: api_key is a query PARAMETER; this script never prints a full URL.

USAGE (in the Codespace — key is already a Codespaces secret, no .env needed):
    echo $WINDSOR_API_KEY        # confirm it is set (non-empty)
    python spikes/probe_linkedin_reality.py                 # default 365-day window
    python spikes/probe_linkedin_reality.py --days 800      # widen if empty
    python spikes/probe_linkedin_reality.py --dry-run       # offline self-test, no network
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter
from datetime import date, timedelta

BASE_URL = "https://connectors.windsor.ai"
CONNECTOR = "linkedin"
LINKEDIN_QUIET_AFTER = date(2025, 11, 4)

# Fields we want a reality check on. Only ids present in the live catalogue are
# actually probed; every id is reported present/missing either way.
TARGET_FIELDS = {
    "keys/dimensions": ["account_name", "currency"],  # date/account_id/campaign_id/campaign are base keys
    "status": ["campaign_status", "status", "campaign_state", "state"],
    "core metrics": ["spend", "impressions", "clicks", "conversions"],
    "ratios (pre-baked; we DERIVE, but probe what LinkedIn returns)": ["cpc", "ctr", "conversion_rate", "cost_per_conversion"],
    "linkedin-specific engagement": ["audience_penetration", "average_dwell_time", "viral_impressions"],
    "revenue / budget / lead (previously ABSENT — re-tested over 1yr)": [
        "conversion_value", "revenue", "external_website_conversions",
        "daily_budget", "total_budget", "cost_per_lead", "lead_group_form_completion_rate",
    ],
    "revenue / budget / CPA / leads — FOUND via grep 2026-07-23 (confirm population)": [
        "conversionvalueinlocalcurrency", "transactionrevenue",
        "campaign_total_budget_amount", "campaign_group_total_budget", "campaign_daily_budget_amount",
        "externalwebsiteconversions", "externalwebsitepostclickconversions",
        "cost_per_externalwebsiteconversions", "oneclickleads", "oneclickleadformopens",
        "average_frequency",
    ],
    "campaign dates (Task 3)": ["campaign_start_date", "campaign_end_date", "start_date", "end_date"],
}
GREP_CONCEPTS = ["status", "start", "end", "date", "conversion", "value", "revenue",
                 "lead", "budget", "cost", "cpc", "penetration", "dwell", "viral",
                 "spend", "impression", "click", "reach", "frequenc"]
STATUS_CANDIDATES = ["campaign_status", "status", "campaign_state", "state"]
START_CANDIDATES = ["campaign_start_date", "start_date", "campaign_start"]
END_CANDIDATES = ["campaign_end_date", "end_date", "campaign_end"]

WITH_DATE_KEYS = ["date", "account_id", "campaign_id", "campaign"]
NODATE_KEYS = ["account_id", "campaign_id", "campaign"]
GRAIN_KEYS = ("account_id", "campaign_id", "date")


# --------------------------------------------------------------------------- #
# Windsor client — fast-fails deterministic errors, retries only transient ones
# --------------------------------------------------------------------------- #
class PullError(Exception):
    """Windsor returned a deterministic 'cannot pull' error (bad field combo/range/account)."""


def _get(path: str, params: dict, *, max_attempts: int = 3):
    import requests
    key = os.environ.get("WINDSOR_API_KEY")
    if not key:
        sys.exit("ERROR: WINDSOR_API_KEY not set. In this Codespace the key is a Codespaces secret — "
                 "check `echo $WINDSOR_API_KEY` shows a value (no .env needed).")
    url, full, attempt = f"{BASE_URL}{path}", {**params, "api_key": key}, 0
    while True:
        attempt += 1
        try:
            r = requests.get(url, params=full, timeout=90)
            if r.status_code < 400:
                return r.json()
            body = r.text[:300]
            low = body.lower()
            if r.status_code == 400:
                raise PullError(f"400 on {path}: {body}")            # bad field/param — don't retry
            if r.status_code in (401, 403):
                raise SystemExit(f"{r.status_code} auth error on {path}: {body}")
            if r.status_code == 500 and ("error pulling data" in low or "invalid response" in low):
                raise PullError(f"500 pull-error on {path}: {body}")  # deterministic — don't retry
            last = f"{r.status_code} on {path}: {body}"               # other 5xx — transient
        except (SystemExit, PullError):
            raise
        except Exception as exc:
            last = f"network/parse on {path}: {exc!r}"
        if attempt >= max_attempts:
            raise PullError(f"gave up after {attempt} attempts — {last}")
        time.sleep(min(8.0, 1.5 ** attempt))


def get_fields(connector: str) -> list[dict]:
    p = _get(f"/{connector}/fields", {})
    return p if isinstance(p, list) else (p.get("fields") or p.get("data") or [])


def make_live_pull(date_from: date, date_to: date):
    def pull(fields: list[str]):
        try:
            p = _get(f"/{CONNECTOR}", {"fields": ",".join(fields),
                                       "date_from": date_from.isoformat(), "date_to": date_to.isoformat()})
            rows = p.get("data", []) if isinstance(p, dict) else (p or [])
            return rows, None
        except PullError as e:
            return None, str(e)
    return pull


# --------------------------------------------------------------------------- #
# Pure analysis
# --------------------------------------------------------------------------- #
def is_empty(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def summarize_field(rows, f):
    total = len(rows)
    non_empty = [r.get(f) for r in rows if not is_empty(r.get(f))]
    distinct = list(dict.fromkeys(non_empty))
    pct = (len(non_empty) / total * 100.0) if total else 0.0
    if total == 0:
        flag = "NO ROWS"
    elif not non_empty:
        flag = "PULLS BUT ALWAYS EMPTY"
    elif len(distinct) == 1:
        flag = f"ALWAYS = {distinct[0]!r}"
    else:
        flag = "OK"
    return {"total": total, "populated": len(non_empty), "pct": pct,
            "distinct": len(distinct), "sample": distinct[:6], "flag": flag}


def distinct_with_counts(rows, f):
    return Counter(str(r.get(f)) for r in rows if not is_empty(r.get(f))).most_common()


def key_tuples(rows, keys):
    return {tuple(r.get(k) for k in keys) for r in rows}


def index_catalogue(cat):
    return {(f.get("id") or f.get("name")): f for f in cat if (f.get("id") or f.get("name"))}


# --------------------------------------------------------------------------- #
# Orchestration (pull_fn is injectable so the dry-run needs no network)
# --------------------------------------------------------------------------- #
def probe_field(pull_fn, present_keys_with, present_keys_no, f):
    """Try [date-keys + f]; if it errors, retry [no-date keys + f]. Returns a result dict."""
    rows, err = pull_fn(present_keys_with + [f])
    if err is None:
        return {"mode": "with-date", "rows": rows, "err": None}
    rows2, err2 = pull_fn(present_keys_no + [f])
    if err2 is None:
        return {"mode": "no-date (campaign attr)", "rows": rows2, "err": None, "date_err": err}
    return {"mode": "FAILED", "rows": None, "err": err2, "date_err": err}


def run(catalogue, pull_fn, date_from, date_to):
    idx = index_catalogue(catalogue)

    def hr(t):
        print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)

    hr(f"CATALOGUE — '{CONNECTOR}'")
    print(f"{len(catalogue)} fields in /{CONNECTOR}/fields   |   window {date_from} → {date_to} "
          f"({(date_to - date_from).days} days; quiet-after {LINKEDIN_QUIET_AFTER})")

    hr("CATALOGUE GREP — real ids matching key concepts (may reveal better ids)")
    for concept in GREP_CONCEPTS:
        hits = [(fid, f.get("type", "?")) for fid, f in idx.items() if concept in fid.lower()]
        if hits:
            print(f"  ~ {concept}: " + ", ".join(f"{h[0]}({h[1]})" for h in sorted(hits)))

    present_with = [k for k in WITH_DATE_KEYS if k in idx]
    present_no = [k for k in NODATE_KEYS if k in idx]

    hr("BASELINE — does a vanilla time-series pull work at all?")
    base_fields = present_with + (["spend"] if "spend" in idx else [])
    base_rows, base_err = pull_fn(base_fields)
    if base_err:
        print(f"  baseline pull FAILED: {base_err}")
        mini = [k for k in ("date", "campaign_id", "spend") if k in idx] or (["date"] if "date" in idx else [])
        mrows, merr = pull_fn(mini)
        if merr:
            print(f"  minimal pull {mini} ALSO failed: {merr}")
            print("  → ACCOUNT / WINDOW / CONNECTION problem, not per-field. Try a narrower window")
            print("    (--days 120 --date-to 2025-11-04) or check the LinkedIn account is still")
            print("    connected/authorised in the Windsor workspace.")
        else:
            print(f"  but minimal pull {mini} worked ({len(mrows)} rows) — a base key field is bad.")
        return
    if not base_rows:
        print(f"  baseline pull returned ZERO rows for {base_fields}.")
        print("  → Window likely entirely after the quiet date. Re-run wider:")
        print("      python spikes/probe_linkedin_reality.py --days 800")
        print("      python spikes/probe_linkedin_reality.py --date-from 2024-11-01 --date-to 2025-11-04")
        return
    base_n = len(base_rows)
    base_keys_n = len(key_tuples(base_rows, GRAIN_KEYS)) or 1
    print(f"  OK — {base_n} rows over {base_keys_n} (account,campaign,date) tuples "
          f"(fan-out ≈ {base_n / base_keys_n:.2f}×). Base fields: {base_fields}")

    results = {}
    for group, fields in TARGET_FIELDS.items():
        for f in fields:
            if f in idx and f not in results and f not in present_with:
                results[f] = probe_field(pull_fn, present_with, present_no, f)
                time.sleep(0.15)

    hr("TASK 1 — POPULATION PROBE  (pullable? + how populated)")
    print(f"{'field':<28}{'type':<9}{'pull mode':<24}{'pop%':>6}{'distinct':>9}   flag/sample")
    print("-" * 78)
    print("  · base keys (baseline pull)")
    for f in base_fields:
        s = summarize_field(base_rows, f)
        note = s["flag"] if s["flag"] != "OK" else f"e.g. {s['sample'][:3]}"
        print(f"    {f:<26}{idx.get(f, {}).get('type', '?'):<9}{'with-date (baseline)':<24}{s['pct']:>5.0f}%{s['distinct']:>9}   {note}")
    for group, fields in TARGET_FIELDS.items():
        present = [f for f in fields if f in idx and f not in present_with]
        if not present:
            continue
        print(f"  · {group}")
        for f in present:
            res = results[f]
            typ = idx[f].get("type", "?")
            if res["err"]:
                print(f"    {f:<26}{typ:<9}{'FAILED TO PULL':<24}{'—':>6}{'—':>9}   {res['err'][:30]}")
                continue
            s = summarize_field(res["rows"], f)
            note = s["flag"] if s["flag"] != "OK" else f"e.g. {s['sample'][:3]}"
            print(f"    {f:<26}{typ:<9}{res['mode']:<24}{s['pct']:>5.0f}%{s['distinct']:>9}   {note}")

    hr("TASK 2 — CAMPAIGN STATUS VALUES")
    status_fields = [f for f in STATUS_CANDIDATES if f in results and not results[f]["err"]]
    if not status_fields:
        failed = [f for f in STATUS_CANDIDATES if f in results and results[f]["err"]]
        print("  No status field returned data.", f"(failed: {failed})" if failed else "")
        print("  Check the CATALOGUE GREP '~ status' line above for the real id.")
    for f in status_fields:
        print(f"\n  '{f}'  (type={idx[f].get('type', '?')}, upstream={idx[f].get('upstream_api_request_name', '')}, "
              f"pulled {results[f]['mode']}):")
        counts = distinct_with_counts(results[f]["rows"], f)
        if not counts:
            print("      (always empty in this window)")
        for val, n in counts:
            print(f"      {val:<26} {n:>6} rows")

    hr("TASK 3 (LinkedIn) — campaign_start_date / campaign_end_date reality")
    for label, cands in (("START", START_CANDIDATES), ("END", END_CANDIDATES)):
        present = [c for c in cands if c in results]
        if not present:
            print(f"\n  {label} date: no field present under {cands}")
        for f in present:
            res = results[f]
            if res["err"]:
                print(f"\n  {label} date '{f}' (type={idx[f].get('type', '?')}): FAILED TO PULL — {res['err'][:70]}")
                continue
            s = summarize_field(res["rows"], f)
            print(f"\n  {label} date '{f}'  (type={idx[f].get('type', '?')}, "
                  f"upstream={idx[f].get('upstream_api_request_name', '')}, pulled {res['mode']}):")
            print(f"      populated {s['pct']:.0f}%  ({s['populated']}/{s['total']} rows), {s['distinct']} distinct, flag={s['flag']}")
            if s["sample"]:
                print(f"      sample: {s['sample'][:5]}")

    hr("EXCEL FEED — id | type | upstream | pull-mode | pop% | flag")
    feed = list(base_fields) + [f for grp in TARGET_FIELDS.values() for f in grp if f in results]
    seen = set()
    for f in feed:
        if f in seen or f not in idx:
            continue
        seen.add(f)
        up, typ = idx[f].get("upstream_api_request_name", ""), idx[f].get("type", "?")
        if f in base_fields:
            s, mode, err = summarize_field(base_rows, f), "with-date", None
        else:
            res = results[f]; err = res["err"]; mode = res["mode"]
            s = None if err else summarize_field(res["rows"], f)
        if err:
            print(f"  {f:<24} | {typ:<8} | {up:<26} | FAILED    | —    | not pullable")
        else:
            print(f"  {f:<24} | {typ:<8} | {up:<26} | {mode:<9} | {s['pct']:>3.0f}% | {s['flag']}")


# --------------------------------------------------------------------------- #
# Offline self-test — synthetic pull_fn: entity attrs fail WITH date, succeed
# WITHOUT date (models real LinkedIn); one engagement field always empty.
# --------------------------------------------------------------------------- #
def _dry_run():
    print(">>> OFFLINE DRY-RUN — synthetic LinkedIn pull_fn, no network <<<")
    catalogue = [
        {"id": "date", "type": "DATE", "upstream_api_request_name": "date"},
        {"id": "account_id", "type": "TEXT", "upstream_api_request_name": "account"},
        {"id": "campaign_id", "type": "TEXT", "upstream_api_request_name": "pivotValue"},
        {"id": "campaign", "type": "TEXT", "upstream_api_request_name": "campaign_name"},
        {"id": "currency", "type": "TEXT", "upstream_api_request_name": "currencyCode"},
        {"id": "campaign_status", "type": "TEXT", "upstream_api_request_name": "status"},
        {"id": "spend", "type": "NUMERIC", "upstream_api_request_name": "costInLocalCurrency"},
        {"id": "impressions", "type": "NUMERIC", "upstream_api_request_name": "impressions"},
        {"id": "clicks", "type": "NUMERIC", "upstream_api_request_name": "clicks"},
        {"id": "conversions", "type": "NUMERIC", "upstream_api_request_name": "externalWebsiteConversions"},
        {"id": "ctr", "type": "PERCENT", "upstream_api_request_name": "ctr"},
        {"id": "cpc", "type": "NUMERIC", "upstream_api_request_name": "costPerClick"},
        {"id": "audience_penetration", "type": "PERCENT", "upstream_api_request_name": "audiencePenetration"},
        {"id": "average_dwell_time", "type": "NUMERIC", "upstream_api_request_name": "averageDwellTime"},
        {"id": "viral_impressions", "type": "NUMERIC", "upstream_api_request_name": "viralImpressions"},
        {"id": "campaign_start_date", "type": "DATE", "upstream_api_request_name": "runSchedule.start"},
        {"id": "campaign_end_date", "type": "DATE", "upstream_api_request_name": "runSchedule.end"},
    ]
    entity_only = {"campaign_status", "campaign_start_date", "campaign_end_date"}
    ts_rows = [
        {"date": "2025-09-01", "account_id": "509", "campaign_id": "c-100", "campaign": "Brand",
         "spend": "12.4", "impressions": "3400", "clicks": "22", "conversions": "0",
         "ctr": "0.0064", "cpc": "0.56", "audience_penetration": "0.08", "average_dwell_time": "1.2", "viral_impressions": ""},
        {"date": "2025-10-01", "account_id": "509", "campaign_id": "c-100", "campaign": "Brand",
         "spend": "9.1", "impressions": "2600", "clicks": "18", "conversions": "0",
         "ctr": "0.0069", "cpc": "0.51", "audience_penetration": "0.07", "average_dwell_time": "1.1", "viral_impressions": ""},
        {"date": "2025-10-15", "account_id": "509", "campaign_id": "c-200", "campaign": "Retarget",
         "spend": "0", "impressions": "0", "clicks": "0", "conversions": "",
         "ctr": "", "cpc": "", "audience_penetration": "", "average_dwell_time": "", "viral_impressions": ""},
    ]
    entity_rows = {
        "campaign_status": [{"account_id": "509", "campaign_id": "c-100", "campaign": "Brand", "campaign_status": "COMPLETED"},
                            {"account_id": "509", "campaign_id": "c-200", "campaign": "Retarget", "campaign_status": "PAUSED"}],
        "campaign_start_date": [{"account_id": "509", "campaign_id": "c-100", "campaign": "Brand", "campaign_start_date": "2025-06-01"},
                                {"account_id": "509", "campaign_id": "c-200", "campaign": "Retarget", "campaign_start_date": "2025-07-01"}],
        "campaign_end_date": [{"account_id": "509", "campaign_id": "c-100", "campaign": "Brand", "campaign_end_date": ""},
                              {"account_id": "509", "campaign_id": "c-200", "campaign": "Retarget", "campaign_end_date": "2025-10-31"}],
    }

    def pull(fields):
        fset = set(fields)
        bad = fset & entity_only
        has_date = "date" in fset
        if bad and has_date:
            return None, f"500 pull-error: cannot segment {sorted(bad)} by date"
        if bad and not has_date:
            f = next(iter(bad))
            return [dict(r) for r in entity_rows[f]], None
        return [{k: r.get(k) for k in fields} for r in ts_rows], None

    run(catalogue, pull, date(2025, 9, 1), date(2025, 11, 30))

    print("\n>>> assertions <<<")
    w, n = ["date", "account_id", "campaign_id", "campaign"], ["account_id", "campaign_id", "campaign"]
    assert probe_field(pull, w, n, "campaign_status")["mode"].startswith("no-date")
    assert dict(distinct_with_counts(probe_field(pull, w, n, "campaign_status")["rows"], "campaign_status")) == {"COMPLETED": 1, "PAUSED": 1}
    assert probe_field(pull, w, n, "spend")["mode"] == "with-date"
    assert summarize_field(ts_rows, "viral_impressions")["flag"] == "PULLS BUT ALWAYS EMPTY"
    assert summarize_field(probe_field(pull, w, n, "campaign_end_date")["rows"], "campaign_end_date")["pct"] == 50.0
    print("all dry-run assertions passed ✔")


def main():
    ap = argparse.ArgumentParser(description="LinkedIn field-reality probe (Tasks 1-3), field-isolating")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--date-from", type=str, default=None)
    ap.add_argument("--date-to", type=str, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.dry_run:
        _dry_run(); return
    date_to = date.fromisoformat(args.date_to) if args.date_to else date.today()
    date_from = date.fromisoformat(args.date_from) if args.date_from else date_to - timedelta(days=args.days)
    catalogue = get_fields(CONNECTOR)
    run(catalogue, make_live_pull(date_from, date_to), date_from, date_to)


if __name__ == "__main__":
    main()
