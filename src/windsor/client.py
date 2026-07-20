import time
from datetime import date

import requests

from common.config import WindsorSettings


class WindsorError(Exception): ...
class WindsorBadRequest(WindsorError): ...   # 400 — never retried
class WindsorAuthError(WindsorError): ...    # 401/403 — never retried
class WindsorServerError(WindsorError): ...  # 5xx / network — retried


class WindsorClient:
    """Read client. SECURITY: api_key is a query param — never log full URLs."""
    MAX_ATTEMPTS = 5

    def __init__(self, settings: WindsorSettings, session=None, sleep=time.sleep):
        self._s = settings
        self._session = session or requests.Session()
        self._sleep = sleep

    def get_fields(self, connector: str) -> list:
        payload = self._get(f"/{connector}/fields")
        return payload if isinstance(payload, list) else payload.get("fields") or payload.get("data") or []

    def get_data(self, connector: str, *, fields: list[str], date_from: date, date_to: date) -> list[dict]:
        payload = self._get(f"/{connector}", params={
            "fields": ",".join(fields),
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
        })
        return payload.get("data", []) if isinstance(payload, dict) else payload

    def _get(self, path: str, params: dict | None = None):
        url = f"{self._s.base_url}{path}"
        params = {**(params or {}), "api_key": self._s.api_key}
        attempt = 0
        while True:
            attempt += 1
            try:
                r = self._session.get(url, params=params, timeout=self._s.timeout_seconds)
                if r.status_code < 400:
                    return r.json()
                if r.status_code == 400:
                    raise WindsorBadRequest(r.text[:300])
                if r.status_code in (401, 403):
                    raise WindsorAuthError(r.text[:300])
                error = WindsorServerError(f"{r.status_code}: {r.text[:300]}")
            except requests.RequestException as exc:
                error = WindsorServerError(f"network: {exc!r}")
            if attempt >= self.MAX_ATTEMPTS:
                raise error
            self._sleep(min(60.0, 2.0 ** attempt))
