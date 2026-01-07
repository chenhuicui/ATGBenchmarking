# -*- coding: utf-8 -*-
"""
Fill time-series CSVs to fixed 1-second grid (default: 0..599 inclusive).
Extra rule:
- If csv is under ".../monkey/..." in its path, apply:
    events_total := floor(events_total / 100)
    and if original events_total in (1..99), result becomes 0 -> set to 1
  (atg_ft unchanged)

Usage:
  python -m src.experiments.usefulness.fill_timeseries_csv \
    --root "/.../src/experiments/usefulness/out" \
    --start 0 --end 599
"""

from __future__ import annotations
import os
import argparse
import shutil
from typing import Optional, Tuple, List

import pandas as pd


TIME_COL_CANDIDATES = [
    "t", "time", "sec", "secs", "second", "seconds",
    "timestamp", "elapsed", "elapsed_sec", "elapsed_secs",
    "wall_time", "wall_time_s", "step"
]


def detect_time_col(df: pd.DataFrame) -> Optional[str]:
    if df is None or df.empty:
        return None

    cols = list(df.columns)

    # 1) name-based
    lower_map = {str(c).strip().lower(): c for c in cols}
    for name in TIME_COL_CANDIDATES:
        if name in lower_map:
            return lower_map[name]

    # 2) heuristic fallback: first numeric column that looks integer-like and non-decreasing
    for c in cols:
        s = pd.to_numeric(df[c], errors="coerce").dropna()
        if s.empty:
            continue
        int_like_ratio = ((s.round().astype("int64") - s).abs() < 1e-6).mean()
        if int_like_ratio < 0.9:
            continue
        if s.is_monotonic_increasing:
            return c

    return None


def is_monkey_csv(path: str) -> bool:
    # robust path check
    parts = [p.lower() for p in os.path.normpath(path).split(os.sep)]
    return "monkey" in parts


def transform_events_total_for_monkey(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    if "events_total" not in df.columns:
        return df

    s = pd.to_numeric(df["events_total"], errors="coerce")
    # keep NaN as NaN
    orig = s.copy()

    # floor division by 100
    scaled = (s / 100.0).apply(lambda x: int(x) if pd.notna(x) else x)

    # if original in [1..99] => scaled would be 0, force to 1
    # keep original == 0 as 0
    mask_force_1 = (orig.notna()) & (orig > 0) & (orig < 100) & (scaled == 0)
    scaled.loc[mask_force_1] = 1

    df = df.copy()
    df["events_total"] = scaled.astype("Int64")  # pandas nullable int
    return df


def fill_one_csv(path: str, start: int = 0, end: int = 599, dry_run: bool = False) -> Tuple[bool, str]:
    try:
        df = pd.read_csv(path)
    except Exception as e:
        return False, f"[READ_FAIL] {path} :: {e}"

    if df.empty:
        return False, f"[EMPTY] {path}"

    time_col = detect_time_col(df)
    if time_col is None:
        return False, f"[NO_TIME_COL] {path} (columns={list(df.columns)})"

    # normalize time to int seconds
    d = df.copy()
    d[time_col] = pd.to_numeric(d[time_col], errors="coerce")
    d = d.dropna(subset=[time_col])
    if d.empty:
        return False, f"[TIME_ALL_NA] {path} (time_col={time_col})"

    d[time_col] = d[time_col].round().astype("int64")
    d = d.sort_values(time_col)

    # keep last row for each second (in case of duplicates)
    d = d.groupby(time_col, as_index=False).last()

    full_seconds = pd.Index(range(int(start), int(end) + 1), name=time_col)
    d2 = d.set_index(time_col).reindex(full_seconds)

    # fill missing seconds: forward-fill; and fill head with first available
    d2 = d2.ffill().bfill()

    d2 = d2.reset_index()

    # apply monkey-only transform AFTER filling (so filled rows consistent too)
    if is_monkey_csv(path):
        d2 = transform_events_total_for_monkey(d2)

    # keep original column order (time col first + original order)
    orig_cols = list(df.columns)
    if time_col in orig_cols:
        orig_cols_no_time = [c for c in orig_cols if c != time_col]
        out_cols = [time_col] + orig_cols_no_time
        out_cols = [c for c in out_cols if c in d2.columns]
        tail = [c for c in d2.columns if c not in out_cols]
        out_cols = out_cols + tail
        d2 = d2[out_cols]

    if dry_run:
        return True, f"[DRY_RUN_OK] {path} time_col={time_col} rows {len(df)} -> {len(d2)} monkey={is_monkey_csv(path)}"

    # backup then write
    bak = path + ".bak"
    if not os.path.exists(bak):
        shutil.copy2(path, bak)

    try:
        d2.to_csv(path, index=False)
    except Exception as e:
        return False, f"[WRITE_FAIL] {path} :: {e}"

    return True, f"[OK] {path} time_col={time_col} rows {len(df)} -> {len(d2)} monkey={is_monkey_csv(path)} (backup={bak})"


def iter_csv_files(root: str) -> List[str]:
    out = []
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith(".csv"):
                out.append(os.path.join(dirpath, fn))
    out.sort()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="Root dir to scan (recursively) for CSVs")
    ap.add_argument("--start", type=int, default=0, help="Start second (inclusive)")
    ap.add_argument("--end", type=int, default=599, help="End second (inclusive)")
    ap.add_argument("--dry_run", action="store_true", help="Only check, do not write back")
    args = ap.parse_args()

    csvs = iter_csv_files(args.root)
    print(f"[SCAN] root={args.root} csv_files={len(csvs)} start={args.start} end={args.end} dry_run={args.dry_run}")

    ok, fail = 0, 0
    for p in csvs:
        success, msg = fill_one_csv(p, start=args.start, end=args.end, dry_run=args.dry_run)
        print(msg)
        if success:
            ok += 1
        else:
            fail += 1

    print(f"[DONE] ok={ok} fail={fail} total={len(csvs)}")


if __name__ == "__main__":
    main()