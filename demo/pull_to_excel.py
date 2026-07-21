"""
Real Windsor sandbox pull -> clean -> Excel export, capped at 100 rows.

This combines:
  - run_pull.py's real WindsorClient call (actually fetches from Windsor)
  - export_excel.py's pandas-to-Excel output

Usage:
    python demo/pull_to_excel.py

Requires (add to pyproject.toml or install directly):
    pip install pandas openpyxl
"""

from datetime import date, timedelta

import pandas as pd

from common.config import WindsorSettings
from etl.normalize import FIELD_MAP, normalize_row
from windsor.client import WindsorClient

ROW_LIMIT = 100
OUTPUT_PATH = "demo/windsor_sample_real.xlsx"


def main() -> None:
    settings = WindsorSettings()  # reads WINDSOR_API_KEY etc. from .env
    client = WindsorClient(settings)

    today = date.today()
    raw_rows = client.get_data(
        "google_ads",
        fields=list(FIELD_MAP.keys()),
        date_from=today - timedelta(days=settings.lookback_days),
        date_to=today,
    )

    if not raw_rows:
        print("No rows returned from Windsor. Check WINDSOR_API_KEY and the sandbox "
              "account has data in the last WINDSOR_LOOKBACK_DAYS window.")
        return

    clean_rows = [normalize_row(r) for r in raw_rows][:ROW_LIMIT]

    df = pd.DataFrame(clean_rows)
    df.to_excel(OUTPUT_PATH, index=False, sheet_name="Google Ads")

    print(
        f"Pulled {len(raw_rows)} raw rows from Windsor, "
        f"wrote {len(clean_rows)} cleaned rows to {OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()
