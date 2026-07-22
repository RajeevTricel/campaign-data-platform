# spikes/list_fields.py  (throwaway) — lists candidates only, NO data pulls
import os, requests

KEY = os.environ["WINDSOR_API_KEY"]
BASE = "https://connectors.windsor.ai"
CONNECTORS = ["linkedin", "facebook"]   # facebook again to catch its date fields

def fields(slug):
    r = requests.get(f"{BASE}/{slug}/fields", params={"api_key": KEY}, timeout=90)
    if r.status_code != 200:
        print(f"  {slug}: HTTP {r.status_code}"); return []
    d = r.json()
    return d.get("data", d) if isinstance(d, dict) else d

for slug in CONNECTORS:
    fs = fields(slug)
    print(f"\n===== {slug} =====")
    print("--- STATUS ---")
    for f in fs:
        fid = (f.get("id") or "").lower()
        if "status" in fid or fid.endswith("_state") or fid == "state":
            print(f"  {f.get('id'):45} | {f.get('name')}")
    print("--- START / END DATE ---")
    for f in fs:
        fid = (f.get("id") or "").lower()
        if ("start" in fid or "end" in fid) and "spend" not in fid:
            print(f"  {f.get('id'):45} | {f.get('name')} | {f.get('type')}")