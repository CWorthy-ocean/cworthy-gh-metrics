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

from github_metrics import collect

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


def _load_config(config_path: Path) -> tuple[list[str], Path, str]:
    with config_path.open() as fh:
        cfg = yaml.safe_load(fh)

    repos = cfg.get("repos") or []
    token = _resolve_token(cfg.get("github_token", "${GITHUB_TOKEN}"))

    db_raw = cfg.get("db_path", "metrics.db")
    db_path = Path(db_raw)
    if not db_path.is_absolute():
        db_path = config_path.parent / db_path

    return repos, db_path, token


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect GitHub metrics.")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    parser.add_argument("--repo", default=None, help="Single repo override")
    parser.add_argument("--token", default=None, help="GitHub token override")
    parser.add_argument("--db", default=None, help="SQLite db path override")
    args = parser.parse_args()

    config_path = Path(args.config) if args.config else Path(__file__).parent / "config.yaml"

    repos, db_path, token = _load_config(config_path)

    if args.repo:
        repos = [args.repo]
    if args.token:
        token = args.token
    if args.db:
        db_path = Path(args.db)

    if not repos:
        log.error("No repos configured. Add entries under 'repos:' in config.yaml.")
        sys.exit(1)

    log.info("Starting collection for %d repo(s) → %s", len(repos), db_path)
    summary = collect(repos, db_path=db_path, token=token)

    errors = [r for r, v in summary.items() if "error" in v]
    if errors:
        log.error("Finished with errors in: %s", errors)
        sys.exit(1)
    log.info("Done.")


if __name__ == "__main__":
    main()
