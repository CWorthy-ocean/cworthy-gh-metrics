"""Orchestration layer: fetch → store for a list of repos."""

from __future__ import annotations

import logging
from pathlib import Path

from .fetch import fetch_all_metrics
from .store import upsert_metrics

log = logging.getLogger(__name__)


def collect(
    repos: list[str],
    data_dir: str | Path,
    token: str,
) -> dict[str, dict[str, int]]:
    """Fetch current GitHub metrics for every repo and persist them.

    Returns a summary dict ``{repo: {metric: row_count}}``.
    """
    summary: dict[str, dict[str, int]] = {}
    for repo in repos:
        log.info("Collecting %s …", repo)
        try:
            metrics = fetch_all_metrics(repo, token=token)
            upsert_metrics(data_dir, repo, metrics)
            summary[repo] = {k: len(v) for k, v in metrics.items()}
            log.info("  %s → %s", repo, summary[repo])
        except Exception as exc:
            log.error("  %s failed: %s", repo, exc)
            summary[repo] = {"error": str(exc)}
    return summary
