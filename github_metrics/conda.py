"""Fetch conda package download statistics from anaconda.org."""

from __future__ import annotations

import datetime

import pandas as pd
import requests


def fetch_conda_metrics(
    package: str,
    channel: str = "conda-forge",
) -> dict[str, pd.DataFrame]:
    """Return a snapshot of total downloads for *package* on *channel*.

    Parameters
    ----------
    package:
        Package name, e.g. ``"roms-tools"``.
    channel:
        Anaconda channel, defaults to ``"conda-forge"``.

    Returns
    -------
    dict with key ``"snapshots"`` — fetched_date, total_downloads
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
    total = data.get("downloads") or sum(
        f.get("ndownloads", 0) for f in data.get("files", [])
    )
    df = pd.DataFrame(
        [
            {
                "fetched_date": datetime.date.today(),
                "total_downloads": total,
            }
        ]
    )
    return {"snapshots": df}
