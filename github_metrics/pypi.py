"""Fetch PyPI download statistics from pypistats.org.

The API returns up to 180 days of daily history with no authentication required.
"""

from __future__ import annotations

import pandas as pd
import requests

_BASE = "https://pypistats.org/api/packages"
_HEADERS = {"User-Agent": "github-metrics-collector"}


def _get(package: str, endpoint: str) -> list[dict]:
    resp = requests.get(f"{_BASE}/{package}/{endpoint}", headers=_HEADERS, timeout=30)
    if not resp.ok:
        try:
            detail = resp.json().get("message", resp.text)
        except Exception:
            detail = resp.text
        raise requests.HTTPError(
            f"{resp.status_code} {resp.reason} — {detail}", response=resp
        )
    return resp.json().get("data", [])


def fetch_pypi_metrics(package: str) -> dict[str, pd.DataFrame]:
    """Return daily PyPI download stats for *package*.

    Returns
    -------
    dict with keys:
        ``"overall"``    — date, downloads  (daily totals, mirrors excluded)
        ``"by_system"``  — date, system, downloads
        ``"by_python"``  — date, python_version, downloads
    """
    # Daily totals — filter to without_mirrors for clean counts
    overall_raw = _get(package, "overall")
    overall = pd.DataFrame(
        [
            {"date": r["date"], "downloads": r["downloads"]}
            for r in overall_raw
            if r.get("category") == "without_mirrors"
        ]
    ).sort_values("date").reset_index(drop=True)

    # By OS/system
    system_raw = _get(package, "system")
    by_system = pd.DataFrame(
        [
            {"date": r["date"], "system": r.get("category", "unknown"), "downloads": r["downloads"]}
            for r in system_raw
            if r.get("downloads", 0) > 0
        ]
    ).sort_values(["date", "system"]).reset_index(drop=True)

    # By Python major version
    python_raw = _get(package, "python_major")
    by_python = pd.DataFrame(
        [
            {"date": r["date"], "python_version": r.get("category", "unknown"), "downloads": r["downloads"]}
            for r in python_raw
            if r.get("downloads", 0) > 0
        ]
    ).sort_values(["date", "python_version"]).reset_index(drop=True)

    return {
        "overall": overall,
        "by_system": by_system,
        "by_python": by_python,
    }
