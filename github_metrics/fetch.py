"""Fetch GitHub traffic and engagement metrics via the REST API.

Requires a token with `repo` scope (traffic endpoints are gated on push access).
"""

from __future__ import annotations

import datetime
import os
from typing import Any

import pandas as pd
import requests

_BASE = "https://api.github.com"


def _session(token: str) -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )
    return s


def _get(session: requests.Session, path: str) -> Any:
    resp = session.get(f"{_BASE}{path}")
    if not resp.ok:
        try:
            detail = resp.json().get("message", resp.text)
        except Exception:
            detail = resp.text
        raise requests.HTTPError(
            f"{resp.status_code} {resp.reason} — {detail}", response=resp
        )
    return resp.json()


# ---------------------------------------------------------------------------
# Individual metric fetchers
# ---------------------------------------------------------------------------


def _views(session: requests.Session, owner: str, name: str) -> pd.DataFrame:
    """Daily page views (count + unique visitors) for the last 14 days."""
    data = _get(session, f"/repos/{owner}/{name}/traffic/views")
    rows = [
        {
            "date": v["timestamp"][:10],
            "views": v["count"],
            "unique_visitors": v["uniques"],
        }
        for v in data.get("views", [])
    ]
    df = pd.DataFrame(rows, columns=["date", "views", "unique_visitors"])
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def _clones(session: requests.Session, owner: str, name: str) -> pd.DataFrame:
    """Daily clones (count + unique cloners) for the last 14 days."""
    data = _get(session, f"/repos/{owner}/{name}/traffic/clones")
    rows = [
        {
            "date": c["timestamp"][:10],
            "clones": c["count"],
            "unique_cloners": c["uniques"],
        }
        for c in data.get("clones", [])
    ]
    df = pd.DataFrame(rows, columns=["date", "clones", "unique_cloners"])
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def _referrers(session: requests.Session, owner: str, name: str) -> pd.DataFrame:
    """Top 10 referring sites over the last 14 days (snapshot, not daily)."""
    data = _get(session, f"/repos/{owner}/{name}/traffic/popular/referrers")
    rows = [
        {
            "fetched_date": datetime.date.today(),
            "referrer": r["referrer"],
            "count": r["count"],
            "uniques": r["uniques"],
        }
        for r in data
    ]
    return pd.DataFrame(rows, columns=["fetched_date", "referrer", "count", "uniques"])


def _paths(session: requests.Session, owner: str, name: str) -> pd.DataFrame:
    """Top 10 popular content paths over the last 14 days (snapshot, not daily)."""
    data = _get(session, f"/repos/{owner}/{name}/traffic/popular/paths")
    rows = [
        {
            "fetched_date": datetime.date.today(),
            "path": p["path"],
            "title": p["title"],
            "count": p["count"],
            "uniques": p["uniques"],
        }
        for p in data
    ]
    return pd.DataFrame(
        rows, columns=["fetched_date", "path", "title", "count", "uniques"]
    )


def _repo_snapshot(session: requests.Session, owner: str, name: str) -> pd.DataFrame:
    """Point-in-time snapshot of stars, forks, watchers, open issues."""
    data = _get(session, f"/repos/{owner}/{name}")
    return pd.DataFrame(
        [
            {
                "fetched_date": datetime.date.today(),
                "stars": data["stargazers_count"],
                "forks": data["forks_count"],
                "watchers": data["subscribers_count"],
                "open_issues": data["open_issues_count"],
            }
        ]
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_metrics(
    repo: str,
    token: str | None = None,
) -> pd.DataFrame:
    """Return a DataFrame of daily traffic metrics for *repo*.

    Columns: date, views, unique_visitors, clones, unique_cloners

    Parameters
    ----------
    repo:
        Full repository name, e.g. ``"CWorthy-ocean/C-Star"``.
    token:
        GitHub personal access token with ``repo`` scope.  Falls back to the
        ``GITHUB_TOKEN`` environment variable when not supplied.
    """
    token = token or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError(
            "A GitHub token is required. Pass token= or set GITHUB_TOKEN."
        )

    owner, name = repo.split("/", 1)
    session = _session(token)

    views = _views(session, owner, name)
    clones = _clones(session, owner, name)
    df = views.merge(clones, on="date", how="outer").sort_values("date").reset_index(drop=True)
    return df


def fetch_all_metrics(
    repo: str,
    token: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Return all available GitHub metrics for *repo* as a dict of DataFrames.

    Keys:
        ``"views"``       — daily views/unique-visitors (last 14 days)
        ``"clones"``      — daily clones/unique-cloners (last 14 days)
        ``"referrers"``   — top referring sites (14-day window snapshot)
        ``"paths"``       — top content paths (14-day window snapshot)
        ``"repo_stats"``  — stars, forks, watchers, open_issues (today)
    """
    token = token or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError(
            "A GitHub token is required. Pass token= or set GITHUB_TOKEN."
        )

    owner, name = repo.split("/", 1)
    session = _session(token)

    return {
        "views": _views(session, owner, name),
        "clones": _clones(session, owner, name),
        "referrers": _referrers(session, owner, name),
        "paths": _paths(session, owner, name),
        "repo_stats": _repo_snapshot(session, owner, name),
    }
