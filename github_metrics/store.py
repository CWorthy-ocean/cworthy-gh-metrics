"""CSV persistence layer with upsert semantics.

Layout on disk:
    data/{owner}/{repo}/{metric}.csv

One file per (repo, metric). Upserts deduplicate on the natural primary key
for each metric type so re-running the job never produces duplicate rows.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

_PRIMARY_KEYS: dict[str, list[str]] = {
    "views":      ["date"],
    "clones":     ["date"],
    "referrers":  ["fetched_date", "referrer"],
    "paths":      ["fetched_date", "path"],
    "repo_stats": ["fetched_date"],
}


def _csv_path(data_dir: str | Path, repo: str, metric: str) -> Path:
    owner, name = repo.split("/", 1)
    return Path(data_dir) / owner / name / f"{metric}.csv"


def upsert_metrics(
    data_dir: str | Path,
    repo: str,
    metrics: dict[str, pd.DataFrame],
) -> None:
    """Merge *metrics* into the CSV store, deduplicating by primary key."""
    for metric, df in metrics.items():
        if df.empty:
            continue
        df = df.copy()
        for col in df.columns:
            if hasattr(df[col].iloc[0], "isoformat"):
                df[col] = df[col].astype(str)

        path = _csv_path(data_dir, repo, metric)
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            existing = pd.read_csv(path, dtype=str)
            df = pd.concat([existing, df.astype(str)], ignore_index=True)
            df = df.drop_duplicates(subset=_PRIMARY_KEYS[metric], keep="last")

        df.to_csv(path, index=False)


def read_metrics(
    data_dir: str | Path,
    repo: str,
    metric: str,
) -> pd.DataFrame:
    """Read all accumulated rows for *repo* / *metric* from the CSV store."""
    path = _csv_path(data_dir, repo, metric)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path).sort_values(_PRIMARY_KEYS[metric]).reset_index(drop=True)
