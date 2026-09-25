"""Audit one locked MA clue on every 2024-26 market day, with block uncertainty.

This reuses the prior locked factor formula and eligibility code without changing
its source file. Overlapping five-day outcomes are predictive statistics, not a
simultaneously executable portfolio or an independent holdout.
"""
from __future__ import annotations

from datetime import date
from hashlib import sha256
from pathlib import Path
import json

import numpy as np
import polars as pl

import ma_clean_research as prior


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/factor_research/ma_research_2026.parquet"
DESTINATION = ROOT / "reports/ma_unified/dense_day_audit.json"
FACTOR = "market_down_day"
SEED = 20260924
REPLICATES = 4000
BLOCK_LENGTHS = (10, 20)


def file_hash(path: Path) -> str:
    h = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def daily_statistics(frame: pl.DataFrame) -> pl.DataFrame:
    score = pl.col(FACTOR)
    x = frame.with_columns(
        ((score > 0) & (score.rank("ordinal", descending=True).over("day") <= 20)).alias("selected")
    )
    return x.group_by("day").agg(
        pl.len().alias("eligible_stocks"),
        pl.col("selected").sum().alias("selected_stocks"),
        pl.col("intent_return").mean().alias("baseline_mean"),
        pl.col("intent_return").filter(pl.col("selected")).mean().alias("signal_mean"),
        (pl.col("intent_return") > 0).filter(pl.col("selected")).mean().alias("signal_up_rate"),
        (~pl.col("entry_fill")).filter(pl.col("selected")).sum().alias("no_entry"),
        pl.col("unclosed_at_horizon").filter(pl.col("selected")).sum().alias("unclosed"),
    ).with_columns(
        (pl.col("signal_mean") - pl.col("baseline_mean")).alias("edge")
    ).sort("day")


def block_interval(values: np.ndarray, block: int, seed: int) -> list[float]:
    """Circular moving-block bootstrap of conditional mean over signal days."""
    rng = np.random.default_rng(seed)
    n = len(values)
    if n < block * 2:
        return [float("nan"), float("nan")]
    blocks = (n + block - 1) // block
    estimates = np.empty(REPLICATES)
    for i in range(REPLICATES):
        starts = rng.integers(0, n, size=blocks)
        indices = (starts[:, None] + np.arange(block)) % n
        sample = values[indices.ravel()[:n]]
        observed = sample[np.isfinite(sample)]
        estimates[i] = float(observed.mean()) if observed.size else np.nan
    estimates = estimates[np.isfinite(estimates)]
    if estimates.size < REPLICATES * 0.99:
        raise ValueError("too many bootstrap samples without signal days")
    return [float(np.quantile(estimates, 0.025)), float(np.quantile(estimates, 0.975))]


def summarize(daily: pl.DataFrame, year: int, eligible_dates: set[date]) -> dict:
    # Every resampled date must have an observable five-day exit within its
    # year. Including the final six dates as artificial no-signal days would
    # change the calendar block distribution.
    dates = sorted(eligible_dates)
    if len(dates) < 40:
        raise ValueError(f"too few market dates for {year}")
    by_day = {row["day"]: row for row in daily.iter_rows(named=True) if row["day"].year == year}
    signal = np.array([by_day[d]["signal_mean"] if d in by_day else np.nan for d in dates], dtype=float)
    edge = np.array([by_day[d]["edge"] if d in by_day else np.nan for d in dates], dtype=float)
    observed = [by_day[d] for d in dates if d in by_day and by_day[d]["selected_stocks"] > 0]
    if not observed:
        raise ValueError(f"no signal days for {year}")
    signal_days = len(observed)
    result = {
        "market_dates": len(dates), "signal_days": signal_days,
        "selected_stocks": sum(int(row["selected_stocks"]) for row in observed),
        "signal_mean": float(np.nanmean(signal)), "edge": float(np.nanmean(edge)),
        "median_signal_day_mean": float(np.nanmedian(signal)),
        "signal_up_rate_mean": float(np.mean([row["signal_up_rate"] for row in observed])),
        "selected_no_entry": sum(int(row["no_entry"]) for row in observed),
        "selected_unclosed": sum(int(row["unclosed"]) for row in observed),
        "after_0p3pct_cost_sensitivity": float(np.nanmean(signal) - 0.003),
        "block_bootstrap": {},
    }
    for block in BLOCK_LENGTHS:
        result["block_bootstrap"][str(block)] = {
            "signal_mean_95pct": block_interval(signal, block, SEED + year * 100 + block),
            "edge_95pct": block_interval(edge, block, SEED + year * 200 + block),
        }
    return result


def main() -> None:
    if DESTINATION.exists():
        raise FileExistsError("preserve existing dense-day audit")
    raw = pl.read_parquet(SOURCE)
    old_step = prior.STEP
    try:
        prior.STEP = 1
        frame, metadata = prior.make_frame(raw, 2, "fresh", date(2024, 1, 1), date(2026, 9, 23))
    finally:
        prior.STEP = old_step
    daily = daily_statistics(frame)
    periods = {}
    for year in (2024, 2025, 2026):
        end = date(year, 12, 31) if year < 2026 else date(2026, 9, 23)
        year_daily = daily.filter((pl.col("day").dt.year() == year)
                                  & (pl.col("day") <= end))
        # The source frame already requires t+6 <= 2026-09-23. For earlier
        # years, remove signal dates whose horizon crosses the year boundary.
        valid_dates = set(frame.filter((pl.col("day").dt.year() == year)
                                       & (pl.col("exit_day") <= end))["day"].unique().to_list())
        year_daily = year_daily.filter(pl.col("day").is_in(valid_dates))
        periods[str(year)] = summarize(year_daily, year, valid_dates)
    output = {
        "posthoc_robustness_audit": True,
        "factor": FACTOR,
        "scope": "2024-2026 already-viewed dates; 2023-12-29 fixed CSI300 cohort",
        "signal": "every market day at t close, same old factor and eligibility",
        "target": "t+1 open to t+6 open; overlapping horizons",
        "bootstrap": {"type": "circular moving-block calendar-day bootstrap",
                      "block_lengths": list(BLOCK_LENGTHS), "replicates": REPLICATES,
                      "seed": SEED, "estimand": "equal-weight mean over triggered days"},
        "source_sha256": file_hash(SOURCE),
        "prior_code_sha256": file_hash(Path(prior.__file__)),
        "all_eligible_metadata": metadata,
        "periods": periods,
    }
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    DESTINATION.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    for year, item in periods.items():
        print(year, "signal_days", item["signal_days"], "mean", item["signal_mean"],
              "edge", item["edge"], "block10_edge_ci", item["block_bootstrap"]["10"]["edge_95pct"])


if __name__ == "__main__":
    main()
