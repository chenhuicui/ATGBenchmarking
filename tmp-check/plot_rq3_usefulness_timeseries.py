# -*- coding: utf-8 -*-
"""
RQ3 Usefulness: Plot 1s time-series curves (0..599) for multiple apps and runs.

CSV columns:
t,cur_activity,ui_hash,unique_activities,unique_ui_states,unique_transitions,
events_total,events_per_sec,activity_change_rate,ui_state_change_rate,crash_count

Metrics (requested):
AC  -> unique_activities (or coverage via config)
UN  -> unique_ui_states
TC  -> unique_transitions (or coverage via config)
EN  -> events_total
ACR -> activity_change_rate
UCR -> ui_state_change_rate

Aggregation:
  - per app: mean over runs
  - across apps: mean ± std (plot band)

Usage:
  python -m src.experiments.usefulness.plot_rq3_usefulness_timeseries \
    --root ".../usefulness/out" \
    --out_dir ".../figures/rq3" \
    --config_json ".../config.json" \
    --show_std \
    --grid \
    --use_coverage
"""

from __future__ import annotations
import os
import glob
import json
import argparse
from collections import defaultdict
from typing import Dict, List, Tuple, Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.ticker import FormatStrFormatter, FuncFormatter

# ---- Global plotting style (PDF embedding + ACM-like serif) ----
plt.rcParams["pdf.fonttype"] = 42
plt.rcParams["ps.fonttype"] = 42
_candidates = ["Linux Libertine O", "Linux Libertine", "Libertinus Serif", "DejaVu Serif"]
_available = {f.name for f in fm.fontManager.ttflist}
for _name in _candidates:
    if _name in _available:
        plt.rcParams["font.family"] = "serif"
        plt.rcParams["font.serif"] = [_name]
        break
else:
    plt.rcParams["font.family"] = "serif"

ALGO_LABEL = {
    "monkey": "Random-based",
    "atg_ft": "ATGBUILDER-based",
}

# requested 6 metrics
METRICS = [
    ("unique_activities", "AC", "Activity Coverage"),
    ("unique_ui_states", "UN", "UI-State Count"),
    ("unique_transitions", "TC", "Transition Coverage"),
    ("events_total", "EN", "Event Count"),
    ("activity_change_rate", "ACR", "Activity Change Rate"),
    ("ui_state_change_rate", "UCR", "UI-State Change Rate"),
]

CSV_REQUIRED_COLS = [
    "t",
    "unique_activities",
    "unique_ui_states",
    "unique_transitions",
    "events_total",
    "activity_change_rate",
    "ui_state_change_rate",
]

FIGSPACE = "\u2007"  # figure space: width close to a digit in many fonts
NBSP     = "\u00A0"  # non-breaking space (备用)

def _pad(prefix: str, s: str) -> str:
    # prefix 里用 FIGSPACE 模拟 “0.” 或 “.” 的宽度
    return prefix + s

def _fmt_ui_state_count_padded(v, pos):
    # 模拟 "0." 的宽度：用两格 figure-space 近似占位
    # 让 "35" 看起来像被 "0." 顶住，从而 bbox 变宽
    vv = int(round(v))
    return _pad(FIGSPACE * 2, f"{vv:02d}")  # 00,05,...,35

def _fmt_event_count_padded(v, pos):
    # 模拟 "." 的宽度：用一格 figure-space 占位
    vv = int(round(v))
    return _pad(FIGSPACE * 1, f"{vv}")      # 0,25,...,175

BBOX_GUARD_TEXT = "0.88"   # 用 8 比较“宽”，更稳；也可用 "0.888"
BBOX_GUARD_X = -0.16       # 往左放一点，确保被 tight bbox 计入

def _add_bbox_guard(ax):
    # alpha=0 仍会被 bbox 计算（重要）
    ax.text(
        BBOX_GUARD_X, 0.5, BBOX_GUARD_TEXT,
        transform=ax.transAxes,
        ha="right", va="center",
        alpha=0.0,
        clip_on=False,
        zorder=0,
    )


def _load_config(config_json: Optional[str]) -> Dict[str, Dict[str, int]]:
    """
    Return mp[app_id] = {"n_acts": int, "n_trans": int}
    """
    if not config_json:
        return {}
    if not os.path.exists(config_json):
        raise FileNotFoundError(f"config_json not found: {config_json}")
    obj = json.load(open(config_json, "r", encoding="utf-8"))
    mp = {}
    for a in obj.get("apps", []):
        app_id = a.get("app_id")
        acts = a.get("activity_list", []) or []
        trans = a.get("transitions", []) or []
        if app_id:
            mp[str(app_id)] = {"n_acts": int(len(acts)), "n_trans": int(len(trans))}
    return mp


def _load_one_timeseries(csv_path: str, t_start: int = 0, t_end: int = 599) -> Optional[pd.DataFrame]:
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    for c in CSV_REQUIRED_COLS:
        if c not in df.columns:
            return None

    df = df.copy()
    df["t"] = pd.to_numeric(df["t"], errors="coerce")
    df = df.dropna(subset=["t"])
    if df.empty:
        return None
    df["t"] = df["t"].round().astype(int)

    # de-dup by t: keep last
    df = df.sort_values("t").groupby("t", as_index=False).last()

    # reindex 0..599 and carry-forward
    full = pd.Index(range(t_start, t_end + 1), name="t")
    df = df.set_index("t").reindex(full).ffill().bfill().reset_index()

    # numeric cast
    for c in CSV_REQUIRED_COLS:
        if c == "t":
            continue
        df[c] = pd.to_numeric(df[c], errors="coerce").ffill().bfill()

    return df


def _discover_apps(root: str) -> List[str]:
    apps = [p for p in os.listdir(root) if os.path.isdir(os.path.join(root, p))]
    apps.sort()
    return apps


def _discover_runs(root: str, app: str, algo: str) -> List[str]:
    pat = os.path.join(root, app, algo, "run_*", "timeseries_1s.csv")
    return sorted(glob.glob(pat))


def _apply_coverage_transform(
        df: pd.DataFrame,
        *,
        app_id: str,
        config_mp: Dict[str, Dict[str, int]],
        use_coverage: bool,
) -> pd.DataFrame:
    """
    If use_coverage:
      unique_activities -> unique_activities / |activity_list|
      unique_transitions -> unique_transitions / |transitions|
    Clip to [0,1].
    """
    if not use_coverage:
        return df
    if app_id not in config_mp:
        # no config: leave as count (but still works)
        return df
    n_acts = max(1, int(config_mp[app_id].get("n_acts", 1)))
    n_trans = max(1, int(config_mp[app_id].get("n_trans", 1)))

    out = df.copy()
    out["unique_activities"] = (out["unique_activities"] / float(n_acts)).clip(0.0, 1.0)
    out["unique_transitions"] = (out["unique_transitions"] / float(n_trans)).clip(0.0, 1.0)
    return out


def _aggregate(
        root: str,
        apps: List[str],
        algos: List[str],
        config_mp: Dict[str, Dict[str, int]],
        use_coverage: bool,
        t_start: int = 0,
        t_end: int = 599,
) -> Dict[str, Dict[str, Dict[str, np.ndarray]]]:
    """
    Scheme B (pooled over runs):
      - Treat each (app, run) as one sample curve.
      - Aggregate across ALL sample curves: mean ± 95% CI.

    Return agg[algo][metric_col] = {mean, band, n}  (band = 95% CI half-width)
    """
    T = (t_end - t_start + 1)
    metric_cols = [m[0] for m in METRICS]

    # all_runs[algo][metric] -> list of (T,) arrays (each is one run curve)
    all_runs = defaultdict(lambda: defaultdict(list))

    for algo in algos:
        for app in apps:
            csvs = _discover_runs(root, app, algo)
            if not csvs:
                continue

            for csv_path in csvs:
                df = _load_one_timeseries(csv_path, t_start=t_start, t_end=t_end)
                if df is None or len(df) != T:
                    continue

                df = _apply_coverage_transform(df, app_id=app, config_mp=config_mp, use_coverage=use_coverage)

                for c in metric_cols:
                    arr = df[c].to_numpy(dtype=np.float64)
                    all_runs[algo][c].append(arr)

    agg = defaultdict(dict)
    for algo in algos:
        for col in metric_cols:
            curves = all_runs[algo].get(col, [])
            if not curves:
                continue
            mat = np.stack(curves, axis=0)  # (N,T)
            mean = mat.mean(axis=0)

            n = mat.shape[0]
            std = mat.std(axis=0, ddof=1) if n >= 2 else np.zeros_like(mean)
            sem = std / np.sqrt(max(n, 1))

            # 95% CI half-width
            band = 1.96 * sem

            agg[algo][col] = {"mean": mean, "std": band, "n_apps": n}  # keep key name for printing
    return agg


def _plot_one_metric(
        t: np.ndarray,
        agg: Dict[str, Dict[str, Dict[str, np.ndarray]]],
        metric_col: str,
        ylabel: str,
        out_pdf: str,
        algos: List[str],
        show_std: bool = True,
        is_rate: bool = False,
        is_coverage: bool = False,
):
    fig, ax = plt.subplots(figsize=(4, 4))

    for algo in algos:
        if algo not in agg or metric_col not in agg[algo]:
            continue
        y = agg[algo][metric_col]["mean"]
        s = agg[algo][metric_col]["std"]
        label = ALGO_LABEL.get(algo, algo)

        ax.plot(t, y, marker="o", markevery=50, label=label, zorder=3)
        if show_std:
            ax.fill_between(t, y - s, y + s, alpha=0.2)

    for ln in ax.lines:
        ln.set_zorder(3)
        ln.set_clip_on(False)

    ax.set_xlim(t.min(), t.max())
    ax.set_xticks([1, 100, 200, 300, 400, 500, 600])
    ax.set_xlabel("Time (s)")

    # ---- special y-axis rules ----
    if metric_col == "unique_ui_states":
        ax.set_ylim(0, 35)
        ax.set_yticks(np.arange(0, 36, 5))
        ax.yaxis.set_major_formatter(FuncFormatter(_fmt_ui_state_count_padded))
    elif metric_col == "events_total":
        ax.set_ylim(0, 175)
        ax.set_yticks(np.arange(0, 176, 25))
        ax.yaxis.set_major_formatter(FuncFormatter(_fmt_event_count_padded))
    elif is_rate or is_coverage:
        ax.yaxis.set_major_formatter(FormatStrFormatter("%.2f"))
        ax.set_ylim(0.02, 1.0)  # lift a bit from 0
        ax.set_yticks(np.arange(0.0, 1.01, 0.2))

    ax.set_ylabel(ylabel)
    ax.grid(True, linestyle="--", color="gray", alpha=0.25)

    leg = ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, 1.15),
        ncol=2,
        frameon=False,
        fontsize=10,
        handlelength=1.6,
        handletextpad=0.6,
        columnspacing=0.8,
        labelspacing=0.4,
        borderpad=0.6,
        fancybox=False,
        framealpha=1.0,
    )
    frame = leg.get_frame()
    frame.set_edgecolor("black")
    frame.set_linewidth(0.8)
    frame.set_facecolor("white")

    fig.tight_layout(rect=[0, 0, 1, 0.94])
    os.makedirs(os.path.dirname(out_pdf), exist_ok=True)
    fig.savefig(out_pdf, dpi=200, bbox_inches="tight")
    plt.close(fig)


def _plot_grid_2x3(
        t: np.ndarray,
        agg: Dict[str, Dict[str, Dict[str, np.ndarray]]],
        out_pdf: str,
        algos: List[str],
        show_std: bool,
        use_coverage: bool,
):
    fig, axes = plt.subplots(2, 3, figsize=(12, 7))
    axes = axes.flatten()

    for i, (col, short, ylabel) in enumerate(METRICS):
        ax = axes[i]
        for algo in algos:
            if algo not in agg or col not in agg[algo]:
                continue
            y = agg[algo][col]["mean"]
            s = agg[algo][col]["std"]
            label = ALGO_LABEL.get(algo, algo)
            ax.plot(t, y, marker="o", markevery=50, label=label, zorder=3)
            if show_std:
                ax.fill_between(t, y - s, y + s, alpha=0.2)

        ax.set_xlim(t.min(), t.max())
        ax.set_xticks([1, 200, 400, 600])
        ax.set_xlabel("Time (s)")
        ax.set_ylabel(ylabel)

        is_rate = col.endswith("_rate")
        is_cov = use_coverage and (col in ["unique_activities", "unique_transitions"])

        # ---- special y-axis rules ----
        if col == "unique_ui_states":
            ax.set_ylim(0, 35)
            ax.set_yticks(np.arange(0, 36, 5))
        elif col == "events_total":
            ax.set_ylim(0, 175)
            ax.set_yticks(np.arange(0, 176, 25))
        elif is_rate or is_cov:
            ax.yaxis.set_major_formatter(FormatStrFormatter("%.2f"))
            ax.set_ylim(0.02, 1.0)  # lift a bit from 0
            ax.set_yticks(np.arange(0.0, 1.01, 0.2))

        ax.grid(True, linestyle="--", color="gray", alpha=0.25)

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles, labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.02),
        ncol=2,
        frameon=False,
        fontsize=11,
        handlelength=1.6,
        handletextpad=0.6,
        columnspacing=0.8,
    )

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    os.makedirs(os.path.dirname(out_pdf), exist_ok=True)
    fig.savefig(out_pdf, dpi=200, bbox_inches="tight")
    plt.close(fig)
def _scalar_from_curve(y: np.ndarray, mode: str, t: np.ndarray) -> float:
    """
    mode:
      - 'endpoint': use last point (t=600)
      - 'auc': trapezoidal area under curve (not normalized)
    """
    if y is None or len(y) == 0:
        return float("nan")
    if mode == "endpoint":
        return float(y[-1])
    if mode == "auc":
        return float(np.trapz(y, x=t))
    raise ValueError(f"unknown mode={mode}")

def _bootstrap_ci_diff(a: np.ndarray, b: np.ndarray, n_boot: int = 2000, seed: int = 123) -> tuple[float, float]:
    """
    Bootstrap 95% CI for (mean(a) - mean(b)).
    a,b are 1D samples (not necessarily paired).
    """
    rng = np.random.default_rng(seed)
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    if len(a) == 0 or len(b) == 0:
        return 0.0, 0.0

    diffs = []
    for _ in range(n_boot):
        sa = rng.choice(a, size=len(a), replace=True)
        sb = rng.choice(b, size=len(b), replace=True)
        diffs.append(float(np.mean(sa) - np.mean(sb)))
    diffs = np.sort(np.asarray(diffs))
    lo = float(np.percentile(diffs, 2.5))
    hi = float(np.percentile(diffs, 97.5))
    return lo, hi

def _bootstrap_ci_ratio(a: np.ndarray, b: np.ndarray, n_boot: int = 2000, seed: int = 123) -> tuple[float, float]:
    """
    Bootstrap 95% CI for relative improvement:
      ((mean(a)-mean(b))/mean(b))*100
    where a=atg_ft samples, b=monkey samples.
    """
    rng = np.random.default_rng(seed)
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    if len(a) == 0 or len(b) == 0:
        return 0.0, 0.0

    ratios = []
    for _ in range(n_boot):
        sa = rng.choice(a, size=len(a), replace=True)
        sb = rng.choice(b, size=len(b), replace=True)
        ma = float(np.mean(sa))
        mb = float(np.mean(sb))
        if abs(mb) < 1e-12:
            # avoid explode; skip this bootstrap sample
            continue
        ratios.append((ma - mb) / mb * 100.0)
    if len(ratios) == 0:
        return 0.0, 0.0
    ratios = np.sort(np.asarray(ratios))
    lo = float(np.percentile(ratios, 2.5))
    hi = float(np.percentile(ratios, 97.5))
    return lo, hi

def _collect_scalar_samples(
    root: str,
    apps: list[str],
    algos: list[str],
    config_mp: dict,
    use_coverage: bool,
    t_start: int,
    t_end: int,
    mode: str,
) -> dict:
    """
    Return samples[algo][metric_col] -> list of scalar (one per run CSV).
    This matches Scheme B pooled-over-runs idea.
    """
    T = (t_end - t_start + 1)
    metric_cols = [m[0] for m in METRICS]
    t = np.arange(t_start + 1, t_end + 2, dtype=np.int64)  # display 1..600

    samples = defaultdict(lambda: defaultdict(list))
    for algo in algos:
        for app in apps:
            csvs = _discover_runs(root, app, algo)
            for csv_path in csvs:
                df = _load_one_timeseries(csv_path, t_start=t_start, t_end=t_end)
                if df is None or len(df) != T:
                    continue
                df = _apply_coverage_transform(df, app_id=app, config_mp=config_mp, use_coverage=use_coverage)

                for col in metric_cols:
                    y = df[col].to_numpy(dtype=np.float64)
                    samples[algo][col].append(_scalar_from_curve(y, mode=mode, t=t))
    return samples

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="usefulness/out root")
    ap.add_argument("--out_dir", required=True)
    ap.add_argument("--config_json", default=None, help="the app config json (for coverage denominators)")
    ap.add_argument("--apps", nargs="*", default=None, help="optional app list; default auto-discover from root")
    ap.add_argument("--algos", nargs="+", default=["monkey", "atg_ft"])
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=599)
    ap.add_argument("--show_std", action="store_true")
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--use_coverage", action="store_true", help="AC/TC converted to ratio using config")
    ap.add_argument("--summary_bar", action="store_true", help="also plot a summary bar chart at t=600 or AUC")
    ap.add_argument("--summary_mode", choices=["endpoint", "auc"], default="endpoint")
    ap.add_argument("--improvement", choices=["relative", "absolute"], default="relative")
    ap.add_argument("--bootstrap", type=int, default=2000)
    args = ap.parse_args()

    config_mp = _load_config(args.config_json)
    apps = args.apps if args.apps else _discover_apps(args.root)
    algos = [a.lower() for a in args.algos]
    t = np.arange(args.start + 1, args.end + 2, dtype=np.int64)  # show as 1..600

    agg = _aggregate(
        root=args.root,
        apps=apps,
        algos=algos,
        config_mp=config_mp,
        use_coverage=bool(args.use_coverage),
        t_start=args.start,
        t_end=args.end,
    )

    # per metric
    for col, short, ylabel in METRICS:
        is_rate = col.endswith("_rate")
        is_cov = bool(args.use_coverage) and (col in ["unique_activities", "unique_transitions"])
        suffix = "cov" if is_cov else "cnt"
        out_pdf = os.path.join(args.out_dir, f"rq3__timeseries__{short}__{suffix}.pdf")
        _plot_one_metric(
            t=t,
            agg=agg,
            metric_col=col,
            ylabel=ylabel,
            out_pdf=out_pdf,
            algos=algos,
            show_std=bool(args.show_std),
            is_rate=is_rate,
            is_coverage=is_cov,
        )

    if args.grid:
        suffix = "cov" if args.use_coverage else "cnt"
        out_pdf = os.path.join(args.out_dir, f"rq3__timeseries__grid_2x3__{suffix}.pdf")
        _plot_grid_2x3(
            t=t, agg=agg, out_pdf=out_pdf,
            algos=algos, show_std=bool(args.show_std),
            use_coverage=bool(args.use_coverage),
        )

    # quick info
    for algo in algos:
        for col, _, _ in METRICS:
            if algo in agg and col in agg[algo]:
                print(f"[OK] algo={algo} col={col} apps_used={agg[algo][col]['n_apps']}")

    print("saved to:", args.out_dir)



if __name__ == "__main__":
    main()
