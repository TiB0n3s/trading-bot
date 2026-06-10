"""SEC EDGAR official disclosure adapter.

SEC EDGAR does not require an account or login. Automated access should include
a clear User-Agent identifying the operator/application.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable
from urllib.request import Request, urlopen

SEC_DATA_BASE_URL = "https://data.sec.gov"
SEC_SUBMISSIONS_PATH = "/submissions/CIK{cik}.json"


@dataclass(frozen=True)
class SecEdgarRequest:
    path: str
    user_agent: str

    @property
    def url(self) -> str:
        return f"{SEC_DATA_BASE_URL}{self.path}"


class SecEdgarService:
    def __init__(
        self,
        *,
        user_agent: str | None = None,
        timeout_seconds: float = 8.0,
        transport: Callable[[SecEdgarRequest], dict[str, Any]] | None = None,
    ):
        self.user_agent = (
            user_agent if user_agent is not None else os.environ.get("SEC_EDGAR_USER_AGENT", "")
        )
        self.timeout_seconds = timeout_seconds
        self.transport = transport or self._default_transport

    @property
    def configured(self) -> bool:
        return bool(str(self.user_agent or "").strip())

    @staticmethod
    def normalize_cik(cik: str | int) -> str:
        return str(cik).strip().lstrip("0").zfill(10)

    def _request(self, path: str) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("SEC_EDGAR_USER_AGENT is not configured")
        return self.transport(SecEdgarRequest(path=path, user_agent=self.user_agent))

    def _default_transport(self, request: SecEdgarRequest) -> dict[str, Any]:
        req = Request(
            request.url,
            headers={
                "User-Agent": request.user_agent,
                "Accept": "application/json",
            },
        )
        with urlopen(req, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def submissions(self, cik: str | int) -> dict[str, Any]:
        cik10 = self.normalize_cik(cik)
        return self._request(SEC_SUBMISSIONS_PATH.format(cik=cik10))

    def recent_filings(
        self,
        cik: str | int,
        *,
        forms: set[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        payload = self.submissions(cik)
        recent = (payload.get("filings") or {}).get("recent") or {}
        accession_numbers = recent.get("accessionNumber") or []
        form_values = recent.get("form") or []
        filing_dates = recent.get("filingDate") or []
        report_dates = recent.get("reportDate") or []
        primary_docs = recent.get("primaryDocument") or []

        rows: list[dict[str, Any]] = []
        allowed_forms = {str(form).upper() for form in forms} if forms else None
        for idx, accession in enumerate(accession_numbers):
            form = str(form_values[idx] if idx < len(form_values) else "").upper()
            if allowed_forms and form not in allowed_forms:
                continue
            rows.append(
                {
                    "cik": self.normalize_cik(cik),
                    "company_name": payload.get("name"),
                    "ticker": (payload.get("tickers") or [None])[0],
                    "form": form,
                    "accession_number": accession,
                    "filing_date": filing_dates[idx] if idx < len(filing_dates) else None,
                    "report_date": report_dates[idx] if idx < len(report_dates) else None,
                    "primary_document": primary_docs[idx] if idx < len(primary_docs) else None,
                    "source": "SEC EDGAR",
                    "source_tier": "official",
                    "source_reliability": "highest",
                    "trusted_source": True,
                }
            )
            if len(rows) >= limit:
                break
        return rows
