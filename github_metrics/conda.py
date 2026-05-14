"""Fetch conda package download statistics from anaconda.org."""

from __future__ import annotations

import datetime

import pandas as pd
import requests


def fetch_conda_metrics(
    package: str,
    channel: str = "conda-forge",
) -> dict[str, pd.DataFrame]:
    """Return download snapshots for *package* on *channel*.

    Returns
    -------
    dict with keys:
        ``"snapshots"``    — fetched_date, total_downloads
        ``"by_platform"``  — fetched_date, platform, downloads
        ``"by_version"``   — fetched_date, version, downloads
    """
    resp = requests.get(
        f"https://api.anaconda.org/package/{channel}/{package}",
        timeout=30,
    )
    if not resp.ok:
        try:
            detail = resp.json().get("error", resp.text)
        except Exception:
            detail = resp.text
        raise requests.HTTPError(
            f"{resp.status_code} {resp.reason} — {detail}", response=resp
        )

    data = resp.json()
    files = data.get("files", [])
    today = datetime.date.today()

    total = data.get("downloads") or sum(f.get("ndownloads", 0) for f in files)

    # Platform breakdown
    platform_counts: dict[str, int] = {}
    for f in files:
        attrs = f.get("attrs") or {}
        platform = attrs.get("subdir") or attrs.get("platform") or "noarch"
        platform_counts[platform] = platform_counts.get(platform, 0) + f.get("ndownloads", 0)

    # Version breakdown
    version_counts: dict[str, int] = {}
    for f in files:
        version = f.get("version", "unknown")
        version_counts[version] = version_counts.get(version, 0) + f.get("ndownloads", 0)

    return {
        "snapshots": pd.DataFrame([{"fetched_date": today, "total_downloads": total}]),
        "by_platform": pd.DataFrame([
            {"fetched_date": today, "platform": p, "downloads": n}
            for p, n in platform_counts.items()
        ]),
        "by_version": pd.DataFrame([
            {"fetched_date": today, "version": v, "downloads": n}
            for v, n in sorted(version_counts.items())
        ]),
    }
