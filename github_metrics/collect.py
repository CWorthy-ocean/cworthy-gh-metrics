"""Orchestration layer: fetch → store for a list of repos."""

from __future__ import annotations

import logging
from pathlib import Path

from .fetch import fetch_all_metrics
from .conda import fetch_conda_metrics
from .pypi import fetch_pypi_metrics
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


def collect_pypi(
    packages: list[str],
    data_dir: str | Path,
) -> dict[str, dict[str, int]]:
    """Fetch PyPI download stats for every package and persist them.

    Stored under ``data/pypi/{package}/{metric}.csv``.
    """
    summary: dict[str, dict[str, int]] = {}
    for package in packages:
        log.info("Collecting PyPI %s …", package)
        try:
            metrics = fetch_pypi_metrics(package)
            upsert_metrics(data_dir, f"pypi/{package}", metrics)
            summary[package] = {k: len(v) for k, v in metrics.items()}
            log.info("  %s → %s", package, summary[package])
        except Exception as exc:
            log.error("  %s failed: %s", package, exc)
            summary[package] = {"error": str(exc)}
    return summary


def collect_conda(
    packages: list[str],
    data_dir: str | Path,
    channel: str = "conda-forge",
) -> dict[str, dict[str, int]]:
    """Fetch conda download snapshots for every package and persist them.

    Stored under ``data/{channel}/{package}/snapshots.csv``.
    Returns a summary dict ``{package: {metric: row_count}}``.
    """
    summary: dict[str, dict[str, int]] = {}
    for package in packages:
        log.info("Collecting conda %s/%s …", channel, package)
        try:
            metrics = fetch_conda_metrics(package, channel=channel)
            upsert_metrics(data_dir, f"{channel}/{package}", metrics)
            summary[package] = {k: len(v) for k, v in metrics.items()}
            log.info("  %s → %s", package, summary[package])
        except Exception as exc:
            log.error("  %s failed: %s", package, exc)
            summary[package] = {"error": str(exc)}
    return summary
