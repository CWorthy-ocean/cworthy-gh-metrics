#!/usr/bin/env python3
"""Entry point for the cron job.

Usage
-----
    python collect.py                     # uses config.yaml next to this file
    python collect.py --config /path/to/config.yaml
    python collect.py --repo CWorthy-ocean/C-Star --token ghp_...

Typical crontab entry (runs daily at 06:00):
    0 6 * * * cd /path/to/github-metrics && python collect.py >> cron.log 2>&1
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path

import yaml

from github_metrics import collect, collect_conda, collect_pypi

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def _resolve_token(raw: str) -> str:
    """Expand ``"${VAR}"`` style env-var references."""
    m = re.fullmatch(r"\$\{(\w+)\}", raw.strip())
    if m:
        val = os.environ.get(m.group(1), "")
        if not val:
            raise SystemExit(
                f"Environment variable {m.group(1)} is not set. "
                "Export it or set github_token literally in config.yaml."
            )
        return val
    return raw


def _load_config(config_path: Path) -> tuple[list[str], list[str], Path, str]:
    with config_path.open() as fh:
        cfg = yaml.safe_load(fh)

    repos = cfg.get("repos") or []
    conda_packages = cfg.get("conda_packages") or []
    pypi_packages = cfg.get("pypi_packages") or []
    token = _resolve_token(cfg.get("github_token", "${TRAFFIC_TOKEN}"))

    data_raw = cfg.get("data_dir", "data")
    data_dir = Path(data_raw)
    if not data_dir.is_absolute():
        data_dir = config_path.parent / data_dir

    return repos, conda_packages, pypi_packages, data_dir, token


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect GitHub metrics.")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    parser.add_argument("--repo", default=None, help="Single repo override")
    parser.add_argument("--token", default=None, help="GitHub token override")
    parser.add_argument("--data-dir", default=None, help="Data directory override")
    args = parser.parse_args()

    config_path = Path(args.config) if args.config else Path(__file__).parent / "config.yaml"

    repos, conda_packages, pypi_packages, data_dir, token = _load_config(config_path)

    if args.repo:
        repos = [args.repo]
    if args.token:
        token = args.token
    if args.data_dir:
        data_dir = Path(args.data_dir)

    errors = []

    if repos:
        log.info("Starting GitHub collection for %d repo(s) → %s", len(repos), data_dir)
        gh_summary = collect(repos, data_dir=data_dir, token=token)
        errors += [r for r, v in gh_summary.items() if "error" in v]

    if conda_packages:
        log.info("Starting conda collection for %d package(s) → %s", len(conda_packages), data_dir)
        conda_summary = collect_conda(conda_packages, data_dir=data_dir)
        errors += [p for p, v in conda_summary.items() if "error" in v]

    if pypi_packages:
        log.info("Starting PyPI collection for %d package(s) → %s", len(pypi_packages), data_dir)
        pypi_summary = collect_pypi(pypi_packages, data_dir=data_dir)
        errors += [p for p, v in pypi_summary.items() if "error" in v]

    if errors:
        log.error("Finished with errors in: %s", errors)
        sys.exit(1)
    log.info("Done.")


if __name__ == "__main__":
    main()
