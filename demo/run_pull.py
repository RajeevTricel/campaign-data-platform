import os
from datetime import date, timedelta

import requests

from common.config import WindsorSettings
from etl.normalize import FIELD_MAP, normalize_row
from windsor.client import WindsorClient

DEFAULT_ENDPOINT = "http://localhost:8000/ingest"


def main() -> None:
    s = WindsorSettings()
    client = WindsorClient(s)
    today = date.today()
    raw_rows = client.get_data(
        "google_ads",
        fields=list(FIELD_MAP.keys()),
        date_from=today - timedelta(days=s.lookback_days),
        date_to=today,
    )
    rows = [normalize_row(r) for r in raw_rows]
    # Decimals -> str so the payload is JSON-serialisable
    payload = [{k: (str(v) if v is not None else None) for k, v in r.items()} for r in rows]
    endpoint = os.environ.get("ENDPOINT_URL", DEFAULT_ENDPOINT)
    resp = requests.post(endpoint, json=payload, timeout=30)
    print(f"pulled {len(raw_rows)} raw, normalized {len(rows)}, endpoint said: {resp.json()}")


if __name__ == "__main__":
    main()
