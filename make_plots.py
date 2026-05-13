#!/usr/bin/env python3
"""Generate traffic plots and update README.md.

For each repo in config.yaml, produces:
  assets/{owner}/{repo}/traffic.png

Then rewrites README.md with an embed of each plot.

Usage:
    python make_plots.py
    python make_plots.py --config /path/to/config.yaml
"""

from __future__ import annotations

import argparse
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
_BLUE_FILL = "#3B82F6"
_GREEN_FILL = "#10B981"
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
    label: str,
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
# Per-repo plot
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
        (axes[0, 0], "Views",           views_df,  "date", "views",           _BLUE),
        (axes[0, 1], "Unique Visitors",  views_df,  "date", "unique_visitors",  _GREEN),
        (axes[1, 0], "Clones",          clones_df, "date", "clones",           _BLUE),
        (axes[1, 1], "Unique Cloners",  clones_df, "date", "unique_cloners",   _GREEN),
    ]

    for ax, title, df, x_col, y_col, color in panels:
        _style_ax(ax, title, color)
        if not df.empty and y_col in df.columns:
            _plot_series(ax, df[x_col], pd.to_numeric(df[y_col]), color, title)
        else:
            _plot_series(ax, pd.Series([], dtype="datetime64[ns]"), pd.Series([], dtype=float), color, title)

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
# README generation
# ---------------------------------------------------------------------------

_README_HEADER = textwrap.dedent("""\
    # GitHub Metrics

    Automated daily collection of traffic and engagement data for
    [C]Worthy GitHub repositories.  Data is fetched via the GitHub API
    and stored as CSV files under [`data/`](data/).  Plots are regenerated
    each time new data is collected.

    ---
""")


def write_readme(repos: list[str], assets_dir: Path, readme_path: Path) -> None:
    sections = []
    for repo in repos:
        owner, name = repo.split("/", 1)
        img = assets_dir / owner / name / "traffic.png"
        img_rel = img.relative_to(readme_path.parent)
        sections.append(
            f"## [{repo}](https://github.com/{repo})\n\n"
            f"![Traffic metrics for {repo}]({img_rel})\n"
        )

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
    data_raw = cfg.get("data_dir", "data")
    data_dir = Path(data_raw)
    if not data_dir.is_absolute():
        data_dir = config_path.parent / data_dir

    assets_dir = config_path.parent / "assets"
    readme_path = config_path.parent / "README.md"

    print("Generating plots…")
    for repo in repos:
        print(f"  {repo}")
        make_repo_plot(data_dir, repo, assets_dir)

    print("Writing README…")
    write_readme(repos, assets_dir, readme_path)

    print("Done.")


if __name__ == "__main__":
    main()
