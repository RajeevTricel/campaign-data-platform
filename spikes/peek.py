# spikes/peek.py  (throwaway — do not build on this file)
# Step 1: LOOK at the data. Run once with a real sandbox key to learn the JSON shape,
# then record the exact field names in spikes/out/discovery_notes.md and delete this.
# SECURITY: prints response bodies only, never the request URL (the api_key is in the query string).
import os, requests, json

key = os.environ["WINDSOR_API_KEY"]
base = "https://connectors.windsor.ai"
print(json.dumps(requests.get(f"{base}/google_ads/fields", params={"api_key": key}).json(), indent=2)[:2000])
data = requests.get(f"{base}/google_ads", params={
    "api_key": key, "fields": "date,campaign,spend,clicks", "date_from": "2026-07-01", "date_to": "2026-07-07",
}).json()
print(json.dumps(data, indent=2)[:2000])
