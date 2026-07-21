"""Pick which rows go in the schema-sample Excel: up to 10 campaigns per account,
capped at 100 rows total per connector, highest-spending campaigns first.

Pure function, no I/O — easy to unit test on its own.
"""
from decimal import Decimal


def sample_per_account(rows: list[dict], per_account: int = 10, connector_cap: int = 100) -> list[dict]:
    if not rows:
        return []

    # Dedupe to one row per (account_id, campaign_id), keeping the latest date.
    latest: dict[tuple, dict] = {}
    for r in rows:
        key = (r.get("account_id"), r.get("campaign_id"))
        current = latest.get(key)
        if current is None or r["date"] > current["date"]:
            latest[key] = r

    # Group by account, sort each account's campaigns by spend descending, take top N.
    by_account: dict = {}
    for r in latest.values():
        by_account.setdefault(r.get("account_id"), []).append(r)

    sampled = []
    for account_rows in by_account.values():
        account_rows.sort(key=lambda r: r.get("spend") or Decimal(0), reverse=True)
        sampled.extend(account_rows[:per_account])

    return sampled[:connector_cap]
