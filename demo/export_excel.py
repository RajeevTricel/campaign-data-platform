"""Extract + Transform -> Excel (first 100 rows) for schema review.

Same pull -> normalize path as run_pull.py, but the sink is an .xlsx instead of
the endpoint. Produced so the owner can eyeball the schema before granting Snowflake
access. When the swap happens (Step 7), this file is discarded like the endpoint.
"""
import pathlib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from common.config import WindsorSettings
from etl.normalize import FIELD_MAP, normalize_row
from windsor.client import WindsorClient

LIMIT = 100
DATA_SHEET = "google_ads_campaign"
OUT_PATH = pathlib.Path("demo/schema_sample_google_ads.xlsx")

# Preferred left-to-right column order; any extra keys (e.g. a future entity_id/level)
# are appended automatically so this survives a schema change.
PREFERRED_ORDER = [
    "platform", "account_id", "campaign_id", "campaign_name", "date", "currency",
    "status", "spend", "impressions", "clicks", "conversions", "revenue", "budget", "loaded_at",
]
TEXT_COLS = {"platform", "account_id", "campaign_id", "campaign_name", "currency", "status", "loaded_at"}
MONEY_COLS = {"spend", "revenue", "budget"}
COUNT_COLS = {"impressions", "clicks", "conversions"}

# Column -> (type, note) shown on the README sheet so the owner can read the schema.
SCHEMA_NOTES = {
    "platform": ("text", "source platform (always google_ads in this extract)"),
    "account_id": ("text", "kept as text to preserve dashes / avoid number coercion"),
    "campaign_id": ("text", "part of the RAW merge key"),
    "campaign_name": ("text", ""),
    "date": ("date", "reporting day; part of the merge key"),
    "currency": ("text", "account currency — needed for FX in the curated layer"),
    "status": ("text", "campaign status"),
    "spend": ("number", "money, account currency"),
    "impressions": ("number", ""),
    "clicks": ("number", ""),
    "conversions": ("number", ""),
    "revenue": ("number", "conversion value"),
    "budget": ("number", "campaign budget"),
    "loaded_at": ("text", "UTC ISO timestamp of normalization"),
}


def _columns(rows: list[dict]) -> list[str]:
    keys = list(rows[0].keys()) if rows else PREFERRED_ORDER
    ordered = [c for c in PREFERRED_ORDER if c in keys]
    ordered += [k for k in keys if k not in ordered]  # any extras, once
    return ordered


def _cell_value(col: str, value):
    if value is None:
        return None
    if col in TEXT_COLS:
        return str(value)
    if isinstance(value, Decimal):
        return float(value)  # Excel stores float; exact Decimal lives in the pipeline
    return value


def build_workbook(rows: list[dict], total_pulled: int, out_path: pathlib.Path) -> pathlib.Path:
    sample = rows[:LIMIT]
    cols = _columns(sample)

    wb = Workbook()
    ws = wb.active
    ws.title = DATA_SHEET

    header_font = Font(name="Arial", bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="305496")
    body_font = Font(name="Arial")

    for j, col in enumerate(cols, start=1):
        c = ws.cell(row=1, column=j, value=col)
        c.font, c.fill = header_font, header_fill
        c.alignment = Alignment(horizontal="left")

    for i, row in enumerate(sample, start=2):
        for j, col in enumerate(cols, start=1):
            c = ws.cell(row=i, column=j, value=_cell_value(col, row.get(col)))
            c.font = body_font
            if col == "date":
                c.number_format = "yyyy-mm-dd"
            elif col in MONEY_COLS:
                c.number_format = "#,##0.00"
            elif col in COUNT_COLS:
                c.number_format = "#,##0"

    ws.freeze_panes = "A2"
    for j, col in enumerate(cols, start=1):
        width = max(len(col), *(len(str(r.get(col) or "")) for r in sample), 8) + 2
        ws.column_dimensions[get_column_letter(j)].width = min(width, 40)

    # README / schema legend sheet
    rd = wb.create_sheet("README")
    meta = [
        ("Source", "Windsor Connectors API — connector: google_ads (sandbox workspace)"),
        ("Contents", f"First {len(sample)} of {total_pulled} normalized campaign-level rows"),
        ("Level", "campaign (one row per campaign per day)"),
        ("Generated (UTC)", datetime.now(timezone.utc).isoformat(timespec="seconds")),
        ("Note", "This is the RAW landing shape. Empty metrics are blank (NULL), not 0."),
    ]
    for i, (k, v) in enumerate(meta, start=1):
        rd.cell(row=i, column=1, value=k).font = Font(name="Arial", bold=True)
        rd.cell(row=i, column=2, value=v).font = body_font

    start = len(meta) + 2
    for j, h in enumerate(("Column", "Type", "Notes"), start=1):
        c = rd.cell(row=start, column=j, value=h)
        c.font, c.fill = header_font, header_fill
    for i, col in enumerate(cols, start=start + 1):
        t, note = SCHEMA_NOTES.get(col, ("", ""))
        rd.cell(row=i, column=1, value=col).font = body_font
        rd.cell(row=i, column=2, value=t).font = body_font
        rd.cell(row=i, column=3, value=note).font = body_font
    rd.column_dimensions["A"].width = 18
    rd.column_dimensions["B"].width = 12
    rd.column_dimensions["C"].width = 60

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return out_path


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
    out = build_workbook(rows, len(rows), OUT_PATH)
    print(f"pulled {len(raw_rows)} raw, normalized {len(rows)}, wrote first "
          f"{min(LIMIT, len(rows))} rows to {out}")


if __name__ == "__main__":
    main()
