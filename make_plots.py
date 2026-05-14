#!/usr/bin/env python3
"""Generate traffic/download plots and update README.md.

For each GitHub repo in config.yaml, produces:
  assets/{owner}/{repo}/traffic.png   — views, unique visitors, clones, unique cloners

For each conda package in config.yaml, produces:
  assets/conda/{package}/downloads.png  — total downloads over time

Then rewrites README.md with embeds of all plots.

Usage:
    python make_plots.py
    python make_plots.py --config /path/to/config.yaml
"""

from __future__ import annotations

import argparse
import math
import textwrap
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd
import yaml

from github_metrics.store import read_metrics

# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------

_BLUE = "#3B82F6"
_GREEN = "#10B981"
_ORANGE = "#F59E0B"
_SPINE_COLOR = "#E5E7EB"
_GRID_COLOR = "#F3F4F6"
_TEXT_COLOR = "#374151"
_TICK_COLOR = "#9CA3AF"


def _style_ax(ax: plt.Axes, title: str, color: str) -> None:
    ax.set_title(title, fontsize=11, fontweight="semibold", color=_TEXT_COLOR, pad=10)
    ax.set_facecolor("white")
    ax.yaxis.grid(True, color=_GRID_COLOR, linewidth=1, zorder=0)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_color(_SPINE_COLOR)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(colors=_TICK_COLOR, labelsize=9)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(mdates.AutoDateLocator()))


def _plot_series(
    ax: plt.Axes,
    dates: pd.Series,
    values: pd.Series,
    color: str,
) -> None:
    if dates.empty:
        ax.text(
            0.5, 0.5, "No data yet",
            transform=ax.transAxes,
            ha="center", va="center",
            color=_TICK_COLOR, fontsize=10,
        )
        return
    ax.fill_between(dates, values, alpha=0.12, color=color, zorder=1)
    ax.plot(dates, values, color=color, linewidth=2, zorder=2)
    ax.plot(dates, values, "o", color=color, markersize=4, zorder=3)


# ---------------------------------------------------------------------------
# GitHub traffic plot (2×2 grid per repo)
# ---------------------------------------------------------------------------


def make_repo_plot(data_dir: Path, repo: str, assets_dir: Path) -> Path:
    views_df = read_metrics(data_dir, repo, "views")
    clones_df = read_metrics(data_dir, repo, "clones")

    for df in (views_df, clones_df):
        if not df.empty and "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])

    fig, axes = plt.subplots(2, 2, figsize=(13, 7))
    fig.patch.set_facecolor("white")
    fig.suptitle(repo, fontsize=14, fontweight="bold", color=_TEXT_COLOR, y=1.01)

    panels = [
        (axes[0, 0], "Views",          views_df,  "date", "views",          _BLUE),
        (axes[0, 1], "Unique Visitors", views_df,  "date", "unique_visitors", _GREEN),
        (axes[1, 0], "Clones",         clones_df, "date", "clones",          _BLUE),
        (axes[1, 1], "Unique Cloners", clones_df, "date", "unique_cloners",  _GREEN),
    ]

    for ax, title, df, x_col, y_col, color in panels:
        _style_ax(ax, title, color)
        if not df.empty and y_col in df.columns:
            _plot_series(ax, df[x_col], pd.to_numeric(df[y_col]), color)
        else:
            _plot_series(ax, pd.Series([], dtype="datetime64[ns]"), pd.Series([], dtype=float), color)

    fig.tight_layout()

    owner, name = repo.split("/", 1)
    out_dir = assets_dir / owner / name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "traffic.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  saved {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# Conda downloads plot (one subplot per package, in a single figure)
# ---------------------------------------------------------------------------


def make_conda_plot(
    data_dir: Path,
    packages: list[str],
    assets_dir: Path,
    channel: str = "conda-forge",
) -> Path:
    n = len(packages)
    ncols = min(n, 2)
    nrows = math.ceil(n / ncols)

    fig, axes = plt.subplots(nrows, ncols, figsize=(7 * ncols, 4 * nrows), squeeze=False)
    fig.patch.set_facecolor("white")
    fig.suptitle(
        f"{channel} — Total Downloads",
        fontsize=14, fontweight="bold", color=_TEXT_COLOR, y=1.01,
    )

    for i, package in enumerate(packages):
        ax = axes[i // ncols][i % ncols]
        df = read_metrics(data_dir, f"{channel}/{package}", "snapshots")
        _style_ax(ax, package, _ORANGE)
        if not df.empty:
            df["fetched_date"] = pd.to_datetime(df["fetched_date"])
            _plot_series(ax, df["fetched_date"], pd.to_numeric(df["total_downloads"]), _ORANGE)
        else:
            _plot_series(ax, pd.Series([], dtype="datetime64[ns]"), pd.Series([], dtype=float), _ORANGE)

    # Hide any unused subplots
    for j in range(n, nrows * ncols):
        axes[j // ncols][j % ncols].set_visible(False)

    fig.tight_layout()

    out_dir = assets_dir / "conda"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "downloads.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  saved {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# README generation
# ---------------------------------------------------------------------------

_README_HEADER = textwrap.dedent("""\
    # GitHub Metrics

    Automated daily collection of traffic and engagement data for
    [C]Worthy GitHub repositories and conda-forge packages.
    Data is fetched via the GitHub and Anaconda APIs and stored as CSV files
    under [`data/`](data/). Plots are regenerated each time new data is collected.

    ---
""")


def write_readme(
    repos: list[str],
    conda_packages: list[str],
    assets_dir: Path,
    readme_path: Path,
) -> None:
    sections = []

    if repos:
        sections.append("## GitHub Traffic\n")
        for repo in repos:
            owner, name = repo.split("/", 1)
            img = assets_dir / owner / name / "traffic.png"
            img_rel = img.relative_to(readme_path.parent)
            sections.append(
                f"### [{repo}](https://github.com/{repo})\n\n"
                f"![Traffic metrics for {repo}]({img_rel})\n"
            )

    if conda_packages:
        sections.append("## Conda Downloads\n")
        img = assets_dir / "conda" / "downloads.png"
        img_rel = img.relative_to(readme_path.parent)
        sections.append(f"![conda-forge download counts]({img_rel})\n")

    readme_path.write_text(_README_HEADER + "\n".join(sections))
    print(f"  wrote {readme_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate traffic plots and README.")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    config_path = Path(args.config) if args.config else Path(__file__).parent / "config.yaml"
    with config_path.open() as fh:
        cfg = yaml.safe_load(fh)

    repos = cfg.get("repos") or []
    conda_packages = cfg.get("conda_packages") or []
    data_raw = cfg.get("data_dir", "data")
    data_dir = Path(data_raw)
    if not data_dir.is_absolute():
        data_dir = config_path.parent / data_dir

    assets_dir = config_path.parent / "assets"
    readme_path = config_path.parent / "README.md"

    print("Generating GitHub traffic plots…")
    for repo in repos:
        print(f"  {repo}")
        make_repo_plot(data_dir, repo, assets_dir)

    if conda_packages:
        print("Generating conda download plot…")
        make_conda_plot(data_dir, conda_packages, assets_dir)

    print("Writing README…")
    write_readme(repos, conda_packages, assets_dir, readme_path)

    print("Done.")


if __name__ == "__main__":
    main()
