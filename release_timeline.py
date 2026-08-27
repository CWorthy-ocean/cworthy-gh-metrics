#!/usr/bin/env python3
"""Draw a timeline of tagged releases across the four CWorthy ROMS-stack repos.

One horizontal lane per repo, a marker at every release tag, labelled with the
tag name. Reads tags from local clones only -- nothing is written to any repo.
Re-run it any time for a fresh picture; add --fetch to pull down new tags first.

    ./release_timeline.py                       # since 2024-07 -> release_timeline.png
    ./release_timeline.py --fetch               # refresh tags from remotes first
    ./release_timeline.py --since all           # the whole history
    ./release_timeline.py --since 2026-01-01    # zoom to a window
    ./release_timeline.py --theme dark -o t.svg # dark figure, vector output

Each lane also reaches back past its first release to the repo's first commit,
drawn as a hollow marker with a solid segment for the pre-release development
period. Details:

* For a fork, "first commit" means the fork's own first commit -- ucla-roms'
  lane starts where CWorthy diverged from CESR-lab, not at UCLA ROMS' 2018 root.
* Committer dates, not author dates: rebased or cherry-picked commits keep an
  author date from before the fork existed (in ucla-roms, months before).
* The axis is still cropped to --since, so a repo that predates the window has
  its dashed segment run off the left edge with no marker; the date is named in
  the lane's sub-label instead.
* A lane with no tagged release inside the window draws its pre-release segment
  all the way to the right edge -- the repo exists, it just has nothing to mark.

Notes on the tag data:

* The window starts at DEFAULT_SINCE (2024-07-01) unless --since says otherwise.
* Only CWorthy-ocean's tags are plotted. ``refs/tags`` is a flat namespace, so a
  clone that has ever fetched a personal fork holds that fork's tags too --
  indistinguishably. Each repo's canonical remote is asked (``git ls-remote``)
  what tags it actually has, and anything else is dropped. An unreachable
  remote is a hard error rather than a silent relaxation of that rule; pass
  --offline to opt into the local tag set instead (for ucla-roms, that fallback
  also drops tags reachable from upstream CESR-lab/main).
* Only release-shaped tag names are plotted (see RELEASE_RE); scratch tags such
  as ``tags/pio`` are dropped. Every drop is reported on stderr -- nothing
  disappears silently. Use --all-tags to keep them.
* Tag dates come from git's ``creatordate``, which is the tagging date for
  annotated tags and the commit date for lightweight ones. ``taggerdate`` is
  empty for lightweight tags, and most tags in these repos are lightweight.
* A tag that exists on the remote but not in the local clone cannot be dated,
  so it is reported on stderr and left off the plot until you --fetch.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt

plt.switch_backend("Agg")  # headless: we only ever save to a file

# --------------------------------------------------------------------------
# What to plot
# --------------------------------------------------------------------------

GIT_ROOT = Path("~/git").expanduser()

# The stack's early history is roms-tools alone; the interesting overlap starts
# mid-2024. Override with --since, or --since all for everything.
DEFAULT_SINCE = date(2024, 7, 1)


@dataclass(frozen=True)
class RepoSpec:
    """A lane on the timeline."""

    key: str
    label: str  # lane label drawn on the figure
    path: Path
    # Candidate names for the canonical remote, most-likely first. --fetch
    # only ever pulls tags from this one: refs/tags is a flat namespace, so
    # fetching every remote would import personal forks' tags as "releases".
    remotes: tuple[str, ...] = ("origin",)
    # Tags reachable from this ref belong to an upstream project, not to us.
    upstream_refs: tuple[str, ...] = ()
    # Used only when none of upstream_refs resolve in the local clone.
    upstream_fallback: frozenset[str] = frozenset()


REPOS: tuple[RepoSpec, ...] = (
    RepoSpec(key="roms-tools", label="roms-tools", path=GIT_ROOT / "roms-tools"),
    RepoSpec(key="C-Star", label="C-Star", path=GIT_ROOT / "C-Star"),
    RepoSpec(
        key="ucla-roms",
        label="ucla-roms\n(CWorthy fork)",
        path=GIT_ROOT / "ucla-roms",
        remotes=("CWorthy-ocean", "origin"),
        upstream_refs=("CESR-lab/main", "upstream/main"),
        upstream_fallback=frozenset({"First_tag", "first_tag", "v2.0.0"}),
    ),
    RepoSpec(key="cstar-forge", label="cstar-forge", path=GIT_ROOT / "cstar-forge"),
)

# Deliberately permissive: anything that starts like a version is a release.
# This keeps the odd-but-real ones (v0.20, v0.08-alpha, 2.6.0.1, 2.6.0.mcb-a)
# and drops only the unambiguous scratch tags (test1, example-tag, tags/pio,
# First_tag). Tightening it silently hides real history, so don't.
RELEASE_RE = re.compile(r"^v?\d")

# --------------------------------------------------------------------------
# Palette (dataviz reference palette, categorical slots 1-4)
# --------------------------------------------------------------------------

THEMES = {
    "light": {
        "surface": "#fcfcfb",
        "text_primary": "#0b0b0b",
        "text_secondary": "#52514e",
        "muted": "#898781",
        "grid": "#e1e0d9",
        "axis": "#c3c2b7",
        "series": {
            "ucla-roms": "#2a78d6",
            "roms-tools": "#eb6834",
            "C-Star": "#1baf7a",
            "cstar-forge": "#eda100",
        },
    },
    "dark": {
        "surface": "#1a1a19",
        "text_primary": "#ffffff",
        "text_secondary": "#c3c2b7",
        "muted": "#898781",
        "grid": "#2c2c2a",
        "axis": "#383835",
        "series": {
            "ucla-roms": "#3987e5",
            "roms-tools": "#d95926",
            "C-Star": "#199e70",
            "cstar-forge": "#c98500",
        },
    },
}

# Type sizes (points) and layout constants.
TAG_FONTSIZE = 7.5
LANE_FONTSIZE = 10.5
AXIS_FONTSIZE = 9
CHAR_WIDTH_EM = 0.62  # mean glyph width as a fraction of the font size
LABEL_GAP_PT = 8.0  # horizontal breathing room between two labels in a tier
MARKER_GAP_PT = 9.0  # vertical gap between the lane line and the first label row
LANE_GAP_PT = 26.0  # clear space between one lane's labels and the next lane's
MIN_LANE_HALF_PT = 20.0  # every lane gets at least this much room above/below
LEFT_MARGIN = 0.13  # room for the lane name and its two-line sub-label
RIGHT_MARGIN = 0.985
TITLE_BAND_IN = 1.0  # inches reserved above the axes for the title block
AXIS_BAND_IN = 0.75  # inches reserved below the axes for the date axis


# --------------------------------------------------------------------------
# Reading tags out of git
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Tag:
    name: str
    when: date


@dataclass(frozen=True)
class Lane:
    """One repo's row: its releases, plus when work on it started."""

    spec: RepoSpec
    tags: list[Tag]
    start: date | None  # first commit; None if it could not be determined


# Output is captured, so an interactive credential prompt would block on stdin
# with nothing on screen -- the script would just appear to hang. Fail instead.
GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


def git(repo: Path, *args: str) -> str:
    """Run a git command in `repo` and return stdout, raising on failure."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env=GIT_ENV,
    )
    return result.stdout.strip()


def git_ok(repo: Path, *args: str) -> bool:
    """Run a git command for its exit status only."""
    return (
        subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=False,
            env=GIT_ENV,
        ).returncode
        == 0
    )


def resolve_upstream_ref(spec: RepoSpec) -> str | None:
    for ref in spec.upstream_refs:
        if git_ok(spec.path, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"):
            return ref
    return None


def fetch_repo(spec: RepoSpec) -> None:
    """Refresh tags from the canonical remote only.

    ``refs/tags`` is a flat namespace shared by every remote, so a blanket
    ``git fetch --all --tags`` would import tags from personal forks and plot
    them as releases. The upstream remote (ucla-roms' CESR-lab) is refreshed
    too -- the fork/upstream split is decided by reachability from its main
    branch, so a stale tracking ref would misclassify new upstream tags -- but
    with --no-tags, so upstream's tags are never pulled into the namespace.
    """
    remotes = set(git(spec.path, "remote").split())

    canonical = next((r for r in spec.remotes if r in remotes), None)
    if canonical is None:
        print(
            f"[{spec.key}] warning: none of {list(spec.remotes)} is a configured "
            f"remote; skipping fetch, plotting the tags already in the clone",
            file=sys.stderr,
        )
    else:
        print(f"[{spec.key}] fetching tags from {canonical}...", file=sys.stderr)
        subprocess.run(
            ["git", "-C", str(spec.path), "fetch", canonical, "--tags", "--quiet"],
            check=False,
            env=GIT_ENV,
        )

    for ref in spec.upstream_refs:
        remote = ref.split("/", 1)[0]
        if remote in remotes:
            print(f"[{spec.key}] refreshing upstream {remote}...", file=sys.stderr)
            subprocess.run(
                ["git", "-C", str(spec.path), "fetch", remote, "--no-tags", "--quiet"],
                check=False,
                env=GIT_ENV,
            )
            break


def canonical_remote(spec: RepoSpec) -> str | None:
    """The CWorthy-ocean remote for this repo, by whatever name it's configured."""
    remotes = set(git(spec.path, "remote").split())
    return next((r for r in spec.remotes if r in remotes), None)


def remote_tag_names(spec: RepoSpec) -> set[str]:
    """Tag names that exist on the CWorthy-ocean remote.

    ``refs/tags`` is flat, so a clone that has ever fetched a personal fork
    carries that fork's tags indistinguishably from CWorthy-ocean's. Asking the
    remote what it actually has is the only reliable way to tell them apart.

    Failing to reach the remote is a hard error, not a warning: silently
    falling back to the local tag set would turn "plot CWorthy's releases"
    into "plot whatever this clone happens to hold". --offline opts into that
    fallback deliberately.

    Membership is by name. A local tag that shares a CWorthy tag's name but
    points at a different commit (git will not clobber an existing tag on
    fetch) would pass this check -- not seen in practice, but it is the limit.
    """
    remote = canonical_remote(spec)
    if remote is None:
        raise SystemExit(
            f"error: {spec.key}: none of {list(spec.remotes)} is a configured "
            f"remote, so tag provenance cannot be checked. Add the CWorthy-ocean "
            f"remote, or re-run with --offline to plot the local tags as-is."
        )

    result = subprocess.run(
        ["git", "-C", str(spec.path), "ls-remote", "--tags", remote],
        capture_output=True,
        text=True,
        check=False,
        env=GIT_ENV,
    )
    if result.returncode != 0:
        detail = (result.stderr.strip().splitlines() or ["unknown error"])[-1]
        raise SystemExit(
            f"error: {spec.key}: could not reach {remote} ({detail}). "
            f"Re-run with --offline to plot the local tags as-is -- note that "
            f"they may include tags pulled from personal forks."
        )

    names = set()
    for line in result.stdout.splitlines():
        _, _, ref = line.partition("refs/tags/")
        if ref and not ref.endswith("^{}"):  # skip peeled annotated-tag lines
            names.add(ref)
    return names


def default_branch_ref(spec: RepoSpec) -> str | None:
    """The canonical remote's default branch, e.g. ``origin/main``."""
    remote = canonical_remote(spec)
    if remote is None:
        return None
    head = f"refs/remotes/{remote}/HEAD"
    result = subprocess.run(
        ["git", "-C", str(spec.path), "symbolic-ref", "-q", head],
        capture_output=True,
        text=True,
        check=False,
        env=GIT_ENV,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip().removeprefix("refs/remotes/")
    for candidate in (f"{remote}/main", f"{remote}/master"):
        if git_ok(
            spec.path, "rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}"
        ):
            return candidate
    return None


def history_start(spec: RepoSpec) -> date | None:
    """When work on this repo began: the date of its earliest commit.

    For a fork, "this repo" means the fork's own work, so upstream history is
    excluded -- ucla-roms' lane should start where CWorthy's work diverged from
    CESR-lab, not at UCLA ROMS' 2018 root commit.

    Uses committer dates, not author dates: a rebased or cherry-picked commit
    keeps its original author date, which in ucla-roms' fork-only range reaches
    back months before the fork actually existed.
    """
    ref = default_branch_ref(spec)
    if ref is None:
        print(
            f"[{spec.key}] warning: no default branch found; "
            f"lane will start at its first release",
            file=sys.stderr,
        )
        return None

    rev_range = [ref]
    upstream_ref = resolve_upstream_ref(spec)
    if upstream_ref is not None:
        rev_range.append(f"^{upstream_ref}")

    result = subprocess.run(
        [
            "git",
            "-C",
            str(spec.path),
            "log",
            "--format=%cd",
            "--date=short",
            *rev_range,
        ],
        capture_output=True,
        text=True,
        check=False,
        env=GIT_ENV,
    )
    dates = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if result.returncode != 0 or not dates:
        print(
            f"[{spec.key}] warning: could not read history for {' '.join(rev_range)}; "
            f"lane will start at its first release",
            file=sys.stderr,
        )
        return None
    return datetime.strptime(min(dates), "%Y-%m-%d").date()


def read_tags(
    spec: RepoSpec, *, all_tags: bool, fetch: bool, offline: bool
) -> list[Tag]:
    """Return the release tags for one repo, reporting every exclusion."""
    if not spec.path.is_dir():
        raise SystemExit(f"error: {spec.key}: no such directory: {spec.path}")
    if not git_ok(spec.path, "rev-parse", "--git-dir"):
        raise SystemExit(f"error: {spec.key}: not a git repository: {spec.path}")

    if fetch:
        fetch_repo(spec)

    on_remote = None if offline else remote_tag_names(spec)

    raw = git(
        spec.path,
        "for-each-ref",
        "--sort=creatordate",
        # strip=2, not refname:short: short renders refs/tags/pio as "tags/pio"
        # when a branch of the same name exists, which is not the tag's name.
        "--format=%(refname:strip=2)%09%(creatordate:short)",
        "refs/tags",
    )

    # The remote tag list already excludes upstream's tags (a fork publishes
    # only its own), so the reachability test is a fallback for when we could
    # not reach the remote.
    upstream_ref = None
    if spec.upstream_refs and on_remote is None:
        upstream_ref = resolve_upstream_ref(spec)
        if upstream_ref is None:
            print(
                f"[{spec.key}] warning: none of {list(spec.upstream_refs)} resolve "
                f"locally; falling back to a hardcoded upstream tag list "
                f"{sorted(spec.upstream_fallback)}",
                file=sys.stderr,
            )

    tags: list[Tag] = []
    dropped_shape: list[str] = []
    dropped_upstream: list[str] = []
    dropped_foreign: list[str] = []

    for line in raw.splitlines():
        if not line.strip():
            continue
        name, _, when = line.partition("\t")
        name, when = name.strip(), when.strip()

        if on_remote is not None and name not in on_remote:
            dropped_foreign.append(name)
            continue

        if spec.upstream_refs and on_remote is None:
            if upstream_ref is not None:
                is_upstream = git_ok(
                    spec.path,
                    "merge-base",
                    "--is-ancestor",
                    f"{name}^{{commit}}",
                    f"{upstream_ref}^{{commit}}",
                )
            else:
                is_upstream = name in spec.upstream_fallback
            if is_upstream:
                dropped_upstream.append(name)
                continue

        if not all_tags and not RELEASE_RE.match(name):
            dropped_shape.append(name)
            continue

        tags.append(Tag(name=name, when=datetime.strptime(when, "%Y-%m-%d").date()))

    if dropped_upstream:
        via = f"reachable from {upstream_ref}" if upstream_ref else "fallback list"
        print(
            f"[{spec.key}] excluded {len(dropped_upstream)} upstream tag(s) "
            f"({via}): {', '.join(dropped_upstream)}",
            file=sys.stderr,
        )
    if dropped_foreign:
        print(
            f"[{spec.key}] excluded {len(dropped_foreign)} tag(s) held locally but "
            f"not published on {canonical_remote(spec)}: {', '.join(dropped_foreign)}",
            file=sys.stderr,
        )
    if dropped_shape:
        print(
            f"[{spec.key}] excluded {len(dropped_shape)} non-release tag name(s) "
            f"(use --all-tags to keep): {', '.join(dropped_shape)}",
            file=sys.stderr,
        )

    # Tags the remote has but this clone doesn't: we have no commit to date
    # them from, so they cannot be plotted until the clone is refreshed.
    if on_remote is not None:
        missing = sorted(
            name
            for name in on_remote - {t.name for t in tags} - set(dropped_shape)
            if all_tags or RELEASE_RE.match(name)
        )
        if missing:
            print(
                f"[{spec.key}] NOTE: {len(missing)} tag(s) exist on the remote but "
                f"not in this clone, so they are missing from the plot: "
                f"{', '.join(missing)} -- re-run with --fetch to include them",
                file=sys.stderr,
            )

    return sorted(tags, key=lambda t: (t.when, t.name))


# --------------------------------------------------------------------------
# Label placement
# --------------------------------------------------------------------------


def assign_tiers(tags: list[Tag], units_per_pt: float) -> list[int]:
    """Greedily pack labels into non-overlapping tiers, in date order.

    Tier 0 is the row closest to the lane; each label goes in the lowest tier
    whose last label ends clear of it. Widths are estimated from the character
    count rather than measured with a renderer -- deterministic, and close
    enough for monospaced-ish tag names.
    """
    tier_right: list[float] = []
    tiers: list[int] = []
    for tag in tags:
        x = mdates.date2num(tag.when)
        half = 0.5 * len(tag.name) * TAG_FONTSIZE * CHAR_WIDTH_EM * units_per_pt
        pad = LABEL_GAP_PT * units_per_pt
        left, right = x - half, x + half
        for tier, occupied in enumerate(tier_right):
            if left > occupied + pad:
                tiers.append(tier)
                tier_right[tier] = right
                break
        else:
            tiers.append(len(tier_right))
            tier_right.append(right)
    return tiers


ROW_PT = TAG_FONTSIZE * 1.5 + 3.0  # height of one row of tag labels


def tier_offset_pt(tier: int) -> tuple[float, int]:
    """Map a tier index to (vertical offset in points, direction: +1 up / -1 down)."""
    direction = 1 if tier % 2 == 0 else -1
    row = tier // 2  # 0-based row within that direction
    return MARKER_GAP_PT + row * ROW_PT, direction


def lane_extent_pt(tiers: list[int]) -> tuple[float, float]:
    """How far a lane's labels reach above and below its line, in points."""
    above = below = MIN_LANE_HALF_PT
    for tier in tiers:
        offset, direction = tier_offset_pt(tier)
        reach = offset + ROW_PT
        if direction > 0:
            above = max(above, reach)
        else:
            below = max(below, reach)
    return above, below


# --------------------------------------------------------------------------
# Plotting
# --------------------------------------------------------------------------


def build_figure(
    lanes: list[Lane],
    *,
    theme: dict,
    fig_width: float,
    title: str,
    since: date | None,
) -> plt.Figure:
    colors = theme["series"]

    all_dates = [mdates.date2num(t.when) for lane in lanes for t in lane.tags]
    # A first commit inside the requested window must fit on the axis; one
    # before it is cropped, and its lane line simply runs off the left edge.
    all_dates += [
        mdates.date2num(lane.start)
        for lane in lanes
        if lane.start is not None and (since is None or lane.start >= since)
    ]
    x_min, x_max = min(all_dates), max(all_dates)
    span = max(x_max - x_min, 1.0)

    axes_width_in = fig_width * (RIGHT_MARGIN - LEFT_MARGIN)

    # x-limits and label widths depend on each other (a wider axis fits wider
    # labels, which changes the padding needed at the edges) -- iterate to a
    # fixed point. Three passes is plenty.
    lo, hi = x_min - 0.03 * span, x_max + 0.03 * span
    tiers_by_lane: list[list[int]] = []
    for _ in range(3):
        units_per_pt = (hi - lo) / (axes_width_in * 72.0)
        tiers_by_lane = [assign_tiers(lane.tags, units_per_pt) for lane in lanes]
        widest = max(
            (len(t.name) for lane in lanes for t in lane.tags),
            default=6,
        )
        edge_pad = 0.5 * widest * TAG_FONTSIZE * CHAR_WIDTH_EM * units_per_pt
        lo = x_min - max(edge_pad, 0.02 * span)
        hi = x_max + max(edge_pad, 0.02 * span)

    # Give every lane exactly the vertical room its own labels need, rather
    # than sizing them all to the deepest lane. The y axis is measured in
    # inches, so a point offset is always offset/72 in data units.
    extents = [lane_extent_pt(tiers) for tiers in tiers_by_lane]
    lane_centers_pt: list[float] = []
    cursor = 0.0  # walking down from the top of the axes
    for above, below in extents:
        cursor += above
        lane_centers_pt.append(cursor)
        cursor += below + LANE_GAP_PT
    axes_height_pt = cursor - LANE_GAP_PT + 10.0  # +10pt so the last lane
    axes_height_in = axes_height_pt / 72.0  # clears the date axis

    fig_height = axes_height_in + TITLE_BAND_IN + AXIS_BAND_IN
    bottom_margin = AXIS_BAND_IN / fig_height
    top_margin = 1.0 - TITLE_BAND_IN / fig_height

    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    fig.subplots_adjust(
        left=LEFT_MARGIN, right=RIGHT_MARGIN, bottom=bottom_margin, top=top_margin
    )
    fig.patch.set_facecolor(theme["surface"])
    ax.set_facecolor(theme["surface"])

    units_per_pt_y = 1.0 / 72.0  # y data units are inches

    for lane, tiers, center_pt in zip(lanes, tiers_by_lane, lane_centers_pt):
        spec, tags = lane.spec, lane.tags
        # y increases upward; lanes were stacked downward from the top.
        y = axes_height_in - center_pt / 72.0
        color = colors[spec.key]

        # Full-width hairline for the lane, with the active span picked out.
        ax.hlines(y, lo, hi, color=theme["grid"], lw=1.0, zorder=1)

        # Pre-release development: first commit to first tag, solid. Runs off
        # the left edge when the repo predates the window (matplotlib clips).
        if lane.start is not None:
            start_x = mdates.date2num(lane.start)
            prerelease_end = mdates.date2num(tags[0].when) if tags else hi
            if start_x < prerelease_end:
                ax.hlines(
                    y,
                    start_x,
                    prerelease_end,
                    color=color,
                    lw=1.6,
                    alpha=0.5,
                    zorder=2,
                )
            # Hollow marker distinguishes "work started" from a release. Only
            # shown for a start inside the window -- lo sits a couple of weeks
            # left of `since` to make room for labels, and a marker in that
            # gap would show a date the user asked to crop.
            if start_x >= lo and (since is None or lane.start >= since):
                ax.plot(
                    start_x,
                    y,
                    marker="o",
                    markersize=5.0,
                    markerfacecolor=theme["surface"],
                    markeredgecolor=color,
                    markeredgewidth=1.4,
                    zorder=5,
                )

        if tags:
            ax.hlines(
                y,
                mdates.date2num(tags[0].when),
                mdates.date2num(tags[-1].when),
                color=color,
                lw=2.0,
                alpha=0.45,
                zorder=2,
            )

        for tag, tier in zip(tags, tiers):
            x = mdates.date2num(tag.when)
            offset_pt, direction = tier_offset_pt(tier)
            offset = direction * offset_pt * units_per_pt_y

            # Leader line from the marker up/down to its label.
            ax.plot(
                [x, x],
                [y, y + offset],
                color=theme["axis"],
                lw=0.6,
                zorder=3,
                solid_capstyle="butt",
            )
            ax.plot(
                x,
                y,
                marker="o",
                markersize=5.5,
                color=color,
                markeredgecolor=theme["surface"],
                markeredgewidth=1.5,
                zorder=5,
            )
            ax.text(
                x,
                y + offset,
                tag.name,
                ha="center",
                va="bottom" if direction > 0 else "top",
                fontsize=TAG_FONTSIZE,
                color=theme["text_primary"],
                zorder=6,
            )

        # Lane label: name in ink, a colour swatch to tie it to the markers.
        ax.text(
            -0.012,
            y,
            spec.label,
            transform=ax.get_yaxis_transform(),
            ha="right",
            va="center",
            fontsize=LANE_FONTSIZE,
            fontweight="bold",
            color=theme["text_primary"],
            linespacing=1.3,
        )
        count = len(tags)
        subtitle = f"{count} release{'s' if count != 1 else ''}"
        if tags:
            subtitle += f" · latest {tags[-1].name}"
        if lane.start is not None:
            # Named here as well as marked on the lane, because a repo that
            # predates the window has its first-commit marker cropped away.
            subtitle += f"\nfirst commit {lane.start.strftime('%b %Y')}"
        ax.text(
            -0.012,
            y - 14.0 / 72.0,
            subtitle,
            transform=ax.get_yaxis_transform(),
            ha="right",
            va="top",
            fontsize=AXIS_FONTSIZE - 1.5,
            color=theme["muted"],
            linespacing=1.4,
        )

    ax.set_xlim(lo, hi)
    ax.set_ylim(0.0, axes_height_in)
    ax.set_yticks([])

    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=(1, 4, 7, 10)))
    ax.xaxis.set_minor_formatter(mdates.DateFormatter("%b"))
    if (hi - lo) < 800:  # under ~2 years, label every month
        ax.xaxis.set_minor_locator(mdates.MonthLocator())

    # If the first January tick is well inside the axis (or there is none at
    # all, for a window within one year), the opening months would carry no
    # year at all -- anchor the starting year at the left edge.
    ticks_in_view = [t for t in ax.xaxis.get_majorticklocs() if lo <= t <= hi]
    if not ticks_in_view or (min(ticks_in_view) - lo) / (hi - lo) > 0.05:
        ax.annotate(
            mdates.num2date(lo).strftime("%Y"),
            xy=(0.0, 0.0),
            xycoords="axes fraction",
            xytext=(0, -22),
            textcoords="offset points",
            ha="left",
            va="top",
            fontsize=AXIS_FONTSIZE,
            fontweight="bold",
            color=theme["text_secondary"],
        )

    ax.grid(axis="x", which="major", color=theme["grid"], lw=0.9, zorder=0)
    ax.grid(axis="x", which="minor", color=theme["grid"], lw=0.5, alpha=0.6, zorder=0)
    ax.set_axisbelow(True)

    # Months sit just under the axis; years sit under the months.
    ax.tick_params(
        axis="x",
        which="major",
        colors=theme["text_secondary"],
        labelsize=AXIS_FONTSIZE,
        pad=16,
        length=0,
    )
    ax.tick_params(
        axis="x",
        which="minor",
        colors=theme["muted"],
        labelsize=AXIS_FONTSIZE - 2,
        pad=2,
        length=3,
        color=theme["axis"],
    )
    for label in ax.get_xticklabels(which="major"):
        label.set_fontweight("bold")

    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(theme["axis"])

    fig.text(
        LEFT_MARGIN,
        1.0 - 0.30 / fig_height,
        title,
        ha="left",
        va="top",
        fontsize=15,
        fontweight="bold",
        color=theme["text_primary"],
    )
    total = sum(len(lane.tags) for lane in lanes)
    fig.text(
        LEFT_MARGIN,
        1.0 - 0.55 / fig_height,
        f"{total} tagged releases · generated {date.today().isoformat()}",
        ha="left",
        va="top",
        fontsize=AXIS_FONTSIZE,
        color=theme["text_secondary"],
    )
    # The lane marks carry two meanings, so name them rather than relying on
    # the reader inferring hollow-vs-filled.
    if any(lane.start is not None for lane in lanes):
        fig.text(
            LEFT_MARGIN,
            1.0 - 0.76 / fig_height,
            "○ first commit  ──  pre-release development      ● tagged release",
            ha="left",
            va="top",
            fontsize=AXIS_FONTSIZE - 1,
            color=theme["muted"],
        )
    return fig


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("release_timeline.png"),
        help="output file; extension picks the format (.png/.svg/.pdf). "
        "Default: release_timeline.png",
    )
    p.add_argument(
        "--repo",
        action="append",
        metavar="KEY=PATH",
        default=[],
        help="override a repo's local path, e.g. --repo C-Star=/tmp/C-Star "
        f"(keys: {', '.join(r.key for r in REPOS)})",
    )
    p.add_argument(
        "--since",
        metavar="YYYY-MM-DD",
        default=DEFAULT_SINCE.isoformat(),
        help=f"drop tags before this date (default: {DEFAULT_SINCE.isoformat()}; "
        f"pass 'all' for the full history)",
    )
    p.add_argument("--until", metavar="YYYY-MM-DD", help="drop tags after this date")
    p.add_argument(
        "--all-tags",
        action="store_true",
        help="keep every tag, including scratch tags with non-release names",
    )
    p.add_argument(
        "--offline",
        action="store_true",
        help="skip the ls-remote provenance check; plots whatever tags the local "
        "clones hold, which may include tags pulled from personal forks",
    )
    p.add_argument(
        "--fetch",
        action="store_true",
        help="refresh tags from each repo's canonical remote first "
        "(writes to the local clones; personal-fork remotes are not fetched)",
    )
    p.add_argument("--theme", choices=("light", "dark"), default="light")
    p.add_argument("--width", type=float, default=16.0, help="figure width in inches")
    p.add_argument("--dpi", type=int, default=200)
    p.add_argument(
        "--title",
        default="Release timeline — CWorthy ROMS stack",
        help="figure title",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    overrides: dict[str, Path] = {}
    for item in args.repo:
        key, sep, path = item.partition("=")
        if not sep:
            raise SystemExit(f"error: --repo expects KEY=PATH, got {item!r}")
        if key not in {r.key for r in REPOS}:
            raise SystemExit(f"error: unknown repo key {key!r}")
        overrides[key] = Path(path).expanduser()

    def parse_date(value: str | None, flag: str) -> date | None:
        if value is None or value.lower() == "all":
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            raise SystemExit(
                f"error: {flag} expects YYYY-MM-DD (or 'all'), got {value!r}"
            ) from None

    since = parse_date(args.since, "--since")
    until = parse_date(args.until, "--until")

    lanes: list[Lane] = []
    for spec in REPOS:
        if spec.key in overrides:
            spec = RepoSpec(**{**spec.__dict__, "path": overrides[spec.key]})
        tags = read_tags(
            spec, all_tags=args.all_tags, fetch=args.fetch, offline=args.offline
        )
        kept = [
            t
            for t in tags
            if (since is None or t.when >= since) and (until is None or t.when <= until)
        ]
        if len(kept) != len(tags):
            print(
                f"[{spec.key}] {len(tags) - len(kept)} tag(s) outside the "
                f"--since/--until window",
                file=sys.stderr,
            )
        start = history_start(spec)
        if until is not None and start is not None and start > until:
            start = None  # repo did not exist yet in this window
        lanes.append(Lane(spec=spec, tags=kept, start=start))

    if not any(lane.tags for lane in lanes):
        raise SystemExit("error: no tags to plot")

    print(file=sys.stderr)
    for lane in lanes:
        tags = lane.tags
        first = f"{tags[0].name} ({tags[0].when})" if tags else "-"
        last = f"{tags[-1].name} ({tags[-1].when})" if tags else "-"
        # "-" covers both "could not read history" (which warns separately
        # above) and "repo did not exist yet in this window".
        started = lane.start.isoformat() if lane.start else "-"
        print(
            f"{lane.spec.key:<14} {len(tags):>3} releases   "
            f"first {first:<22} last {last:<22} history from {started}",
            file=sys.stderr,
        )

    fig = build_figure(
        lanes,
        theme=THEMES[args.theme],
        fig_width=args.width,
        title=args.title,
        since=since,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        args.output,
        dpi=args.dpi,
        facecolor=fig.get_facecolor(),
    )
    print(f"\nwrote {args.output.resolve()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
