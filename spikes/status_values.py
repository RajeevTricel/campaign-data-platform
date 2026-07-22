# spikes/status_values.py  (throwaway) — run after picking ids
import os, requests
KEY = os.environ["WINDSOR_API_KEY"]
BASE = "https://connectors.windsor.ai"

PICK = {
    "google_ads": "campaign_status",
    "facebook":   "campaign_effective_status",   # also try "campaign_status"
    "linkedin":   "campaign_group_status",
}

for slug, fid in PICK.items():
    if "PUT_ID" in fid:
        continue
    rows = requests.get(f"{BASE}/{slug}", params={
        "api_key": KEY,
        "fields": f"date,campaign,clicks,spend,{fid}",
        "date_preset": "last_30d",
    }, timeout=90).json().get("data", []) or []
    vals = sorted({str(r.get(fid)) for r in rows if fid in r})
    print(f"{slug}.{fid}: {len(rows)} rows -> {vals}")