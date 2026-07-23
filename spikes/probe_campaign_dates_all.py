#!/usr/bin/env python3
"""
probe_campaign_dates_all.py  (v2 — field-isolating)
===================================================
TASK 3 — for EACH connector (google_ads, facebook, linkedin): does Windsor expose
a campaign START-date and END-date field, and do real dates actually pull in?

Campaign start/end dates are per-CAMPAIGN entity attributes. On some connectors
(LinkedIn especially) they CANNOT be requested alongside the daily `date` segment
— doing so makes the upstream API error and Windsor returns a 500 for the whole
request. So each date field is probed on its own, and if it fails WITH `date`, it
is retried WITHOUT `date` (campaign grain). A field that only works without `date`
is confirmed to be a per-campaign attribute.

Windows: recent (short) for the active platforms — enough to see active campaigns'
dates and small enough to stay under Windsor's ~100k-char response cap; wide for
LinkedIn (quiet after 2025-11-04).

SECURITY: api_key is a query param; this script never prints a full URL.

USAGE (Codespace — key is a Codespaces secret, no .env needed):
    echo $WINDSOR_API_KEY
    python spikes/probe_campaign_dates_all.py
    python spikes/probe_campaign_dates_all.py --active-days 30 --linkedin-days 500
    python spikes/probe_campaign_dates_all.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, timedelta

BASE_URL = "https://connectors.windsor.ai"
LINKEDIN_QUIET_AFTER = date(2025, 11, 4)
CONNECTORS = ["google_ads", "facebook", "linkedin"]

START_CANDIDATES = {
    "google_ads": ["start_date", "campaign_start_date", "campaign_start"],
    "facebook":   ["campaign_start_time", "campaign_start_date", "start_time", "start_date", "campaign_start"],
    "linkedin":   ["campaign_start_date", "start_date", "campaign_start"],
}
END_CANDIDATES = {
    "google_ads": ["end_date", "campaign_end_date", "campaign_end"],
    "facebook":   ["campaign_stop_time", "campaign_end_date", "stop_time", "end_time", "end_date", "campaign_end"],
    "linkedin":   ["campaign_end_date", "end_date", "campaign_end"],
}
DATE_GREP = ["start", "end", "date", "schedule", "flight", "duration", "begin", "finish", "launch", "stop", "time"]
WITH_DATE_KEYS = ["date", "account_id", "campaign_id", "campaign"]
NODATE_KEYS = ["account_id", "campaign_id", "campaign"]
GRAIN_KEYS = ("account_id", "campaign_id", "date")


class PullError(Exception):
    """Deterministic 'cannot pull' error from Windsor (bad field combo/range/account)."""


def _get(path, params, *, max_attempts=3):
    import requests
    key = os.environ.get("WINDSOR_API_KEY")
    if not key:
        sys.exit("ERROR: WINDSOR_API_KEY not set. In this Codespace the key is a Codespaces secret — "
                 "check `echo $WINDSOR_API_KEY` (no .env needed).")
    url, full, attempt = f"{BASE_URL}{path}", {**params, "api_key": key}, 0
    while True:
        attempt += 1
        try:
            r = requests.get(url, params=full, timeout=90)
            if r.status_code < 400:
                return r.json()
            body, low = r.text[:300], r.text[:300].lower()
            if r.status_code == 400:
                raise PullError(f"400 on {path}: {body}")
            if r.status_code in (401, 403):
                raise SystemExit(f"{r.status_code} auth error on {path}: {body}")
            if r.status_code == 500 and ("error pulling data" in low or "invalid response" in low):
                raise PullError(f"500 pull-error on {path}: {body}")
            last = f"{r.status_code} on {path}: {body}"
        except (SystemExit, PullError):
            raise
        except Exception as exc:
            last = f"network/parse on {path}: {exc!r}"
        if attempt >= max_attempts:
            raise PullError(f"gave up after {attempt} attempts — {last}")
        time.sleep(min(8.0, 1.5 ** attempt))


def get_fields(connector):
    p = _get(f"/{connector}/fields", {})
    return p if isinstance(p, list) else (p.get("fields") or p.get("data") or [])


def make_live_pull(connector, date_from, date_to):
    def pull(fields):
        try:
            p = _get(f"/{connector}", {"fields": ",".join(fields),
                                       "date_from": date_from.isoformat(), "date_to": date_to.isoformat()})
            return (p.get("data", []) if isinstance(p, dict) else (p or [])), None
        except PullError as e:
            return None, str(e)
    return pull


def is_empty(v):
    return v is None or (isinstance(v, str) and v.strip() == "")


def population(rows, f):
    total = len(rows)
    ne = [r.get(f) for r in rows if not is_empty(r.get(f))]
    distinct = list(dict.fromkeys(ne))
    return {"total": total, "populated": len(ne),
            "pct": (len(ne) / total * 100.0) if total else 0.0, "distinct": len(distinct), "sample": distinct[:5]}


def index_catalogue(cat):
    return {(f.get("id") or f.get("name")): f for f in cat if (f.get("id") or f.get("name"))}


def probe_field(pull_fn, keys_with, keys_no, f):
    rows, err = pull_fn(keys_with + [f])
    if err is None:
        return {"mode": "with-date", "rows": rows, "err": None}
    rows2, err2 = pull_fn(keys_no + [f])
    if err2 is None:
        return {"mode": "no-date (campaign attr)", "rows": rows2, "err": None}
    return {"mode": "FAILED", "rows": None, "err": err2}


def verdict(pop):
    if pop["total"] == 0:
        return "NO ROWS in window"
    if pop["pct"] == 0.0:
        return "PRESENT but ALWAYS EMPTY"
    if pop["pct"] < 100.0:
        return f"PRESENT, populated {pop['pct']:.0f}% (partial)"
    return "PRESENT & fully populated"


def probe_connector(connector, active_days, linkedin_days, *, offline=None):
    print("\n" + "#" * 78 + f"\n# CONNECTOR: {connector}\n" + "#" * 78)
    if connector == "linkedin":
        date_to, date_from = date.today(), date.today() - timedelta(days=linkedin_days)
        wnote = f"(wide — LinkedIn quiet after {LINKEDIN_QUIET_AFTER})"
    else:
        date_to, date_from = date.today(), date.today() - timedelta(days=active_days)
        wnote = "(recent — dates repeat per campaign daily)"

    if offline is not None:
        catalogue, pull_fn = offline
    else:
        try:
            catalogue = get_fields(connector)
        except (SystemExit, PullError) as e:
            print(f"  !! /fields failed — connector likely not connected: {e}")
            return
        pull_fn = make_live_pull(connector, date_from, date_to)

    idx = index_catalogue(catalogue)
    print(f"catalogue: {len(catalogue)} fields   |   window {date_from} → {date_to} {wnote}")

    print("\n  date-like fields in the catalogue:")
    shown = set()
    for concept in DATE_GREP:
        for fid, f in sorted(idx.items()):
            if concept in fid.lower() and fid not in shown:
                shown.add(fid)
                print(f"      {fid:<30} type={f.get('type', '?'):<8} upstream={f.get('upstream_api_request_name', '')}")
    if not shown:
        print("      (none matched — inspect the raw catalogue)")

    keys_with = [k for k in WITH_DATE_KEYS if k in idx]
    keys_no = [k for k in NODATE_KEYS if k in idx]

    for label, cands in (("START", START_CANDIDATES[connector]), ("END", END_CANDIDATES[connector])):
        present = [c for c in cands if c in idx]
        if not present:
            print(f"\n  {label} DATE: NO FIELD present under {cands}")
            continue
        for fid in present:
            res = probe_field(pull_fn, keys_with, keys_no, fid)
            print(f"\n  {label} DATE '{fid}'  type={idx[fid].get('type', '?')}  "
                  f"upstream={idx[fid].get('upstream_api_request_name', '')}")
            if res["err"]:
                print(f"      verdict: FAILED TO PULL (present in catalogue, errors on pull) — {res['err'][:80]}")
                continue
            pop = population(res["rows"], fid)
            print(f"      pulled: {res['mode']}   →   {verdict(pop)}  "
                  f"({pop['populated']}/{pop['total']} rows, {pop['distinct']} distinct)")
            if pop["sample"]:
                print(f"      sample: {pop['sample']}")
            time.sleep(0.15)


def _dry_run():
    print(">>> OFFLINE DRY-RUN — synthetic per-connector pull_fn, no network <<<")

    # google_ads: start/end pull fine WITH date (GAQL exposes them as segments)
    ga_cat = [{"id": i, "type": "DATE" if "date" in i else "TEXT",
               "upstream_api_request_name": f"campaign.{i}"} for i in
              ["date", "account_id", "campaign_id", "campaign", "campaign_start_date", "campaign_end_date"]]
    ga_ts = [{"date": "2026-07-10", "account_id": "612", "campaign_id": "g1", "campaign": "Brand",
              "campaign_start_date": "2024-01-15", "campaign_end_date": ""},
             {"date": "2026-07-10", "account_id": "612", "campaign_id": "g2", "campaign": "Promo",
              "campaign_start_date": "2026-06-01", "campaign_end_date": "2026-08-31"}]

    def ga_pull(fields):
        return [{k: r.get(k) for k in fields} for r in ga_ts], None

    # facebook: only start_time present, and it errors WITH date, works WITHOUT (present but empty)
    fb_cat = [{"id": i, "type": "DATE" if i in ("date",) else "TEXT",
               "upstream_api_request_name": i} for i in ["date", "account_id", "campaign_id", "campaign", "start_time"]]

    def fb_pull(fields):
        if "start_time" in fields and "date" in fields:
            return None, "500 pull-error: cannot request start_time with date segment"
        if "start_time" in fields:
            return [{"account_id": "act", "campaign_id": "f1", "campaign": "M", "start_time": ""}], None
        return [{k: r.get(k) for k in fields} for r in
                [{"date": "2026-07-15", "account_id": "act", "campaign_id": "f1", "campaign": "M"}]], None

    # linkedin: both present, error WITH date, work WITHOUT; end mostly empty
    li_cat = [{"id": i, "type": "DATE", "upstream_api_request_name": f"runSchedule.{i}"} for i in
              ["date", "account_id", "campaign_id", "campaign", "campaign_start_date", "campaign_end_date"]]
    li_entity = {"campaign_start_date": [{"account_id": "509", "campaign_id": "l1", "campaign": "B", "campaign_start_date": "2025-06-01"}],
                 "campaign_end_date": [{"account_id": "509", "campaign_id": "l1", "campaign": "B", "campaign_end_date": ""}]}

    def li_pull(fields):
        ent = {"campaign_start_date", "campaign_end_date"} & set(fields)
        if ent and "date" in fields:
            return None, "500 pull-error: cannot segment campaign dates by date"
        if ent:
            f = next(iter(ent))
            return [dict(r) for r in li_entity[f]], None
        return [{k: r.get(k) for k in fields} for r in
                [{"date": "2025-10-01", "account_id": "509", "campaign_id": "l1", "campaign": "B"}]], None

    probe_connector("google_ads", 14, 400, offline=(ga_cat, ga_pull))
    probe_connector("facebook", 14, 400, offline=(fb_cat, fb_pull))
    probe_connector("linkedin", 14, 400, offline=(li_cat, li_pull))

    print("\n>>> assertions <<<")
    assert probe_field(ga_pull, ["date", "account_id", "campaign_id", "campaign"], ["account_id", "campaign_id", "campaign"], "campaign_start_date")["mode"] == "with-date"
    r = probe_field(li_pull, ["date", "account_id", "campaign_id", "campaign"], ["account_id", "campaign_id", "campaign"], "campaign_start_date")
    assert r["mode"].startswith("no-date") and population(r["rows"], "campaign_start_date")["pct"] == 100.0
    rf = probe_field(fb_pull, ["date", "account_id", "campaign_id", "campaign"], ["account_id", "campaign_id", "campaign"], "start_time")
    assert rf["mode"].startswith("no-date") and population(rf["rows"], "start_time")["pct"] == 0.0
    print("all dry-run assertions passed ✔")


def main():
    ap = argparse.ArgumentParser(description="Campaign start/end date probe across connectors (Task 3)")
    ap.add_argument("--active-days", type=int, default=14)
    ap.add_argument("--linkedin-days", type=int, default=400)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.dry_run:
        _dry_run(); return
    for c in CONNECTORS:
        probe_connector(c, args.active_days, args.linkedin_days)


if __name__ == "__main__":
    main()
