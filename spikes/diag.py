# spikes/diag.py  (throwaway)
import os, requests
KEY = os.environ["WINDSOR_API_KEY"]; BASE = "https://connectors.windsor.ai"

def pull(slug, fields, preset="last_year"):
    r = requests.get(f"{BASE}/{slug}", params={
        "api_key": KEY, "fields": fields, "date_preset": preset}, timeout=120)
    try: return r.json().get("data", []) or []
    except Exception: return []

def vals(rows, fid): return sorted({str(r.get(fid)) for r in rows if fid in r})

# 1) Does LinkedIn return ANY data at all?
for p in ("last_30d", "last_year"):
    print(f"linkedin baseline {p}: {len(pull('linkedin','date,campaign,clicks,spend',p))} rows")

# 2) LinkedIn status: try the right id, with metrics and without
for fid in ("campaign_status", "campaign_group_status"):
    r1 = pull("linkedin", f"date,campaign,clicks,spend,{fid}")
    r2 = pull("linkedin", f"campaign,{fid}")            # no metrics = entity-style pull
    print(f"linkedin {fid}  +metrics: {len(r1)} rows {vals(r1,fid)} | no-metrics: {len(r2)} rows {vals(r2,fid)}")

# 3) Wide window to surface PAUSED/REMOVED (the 'show paused too' test)
for slug, fid in (("google_ads","campaign_status"),
                  ("facebook","campaign_status"),
                  ("facebook","campaign_effective_status")):
    r = pull(slug, f"date,campaign,clicks,spend,{fid}")
    print(f"{slug}.{fid} last_year: {len(r)} rows -> {vals(r,fid)}")

# 4) Facebook end date is 'stop_time', not 'end'
for fid in ("campaign_start_time", "campaign_stop_time"):
    r = pull("facebook", f"campaign,{fid}")
    print(f"facebook {fid}: {len(r)} rows -> sample {r[:1]}")