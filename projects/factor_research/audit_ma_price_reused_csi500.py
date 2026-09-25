"""Post-selection diagnostic of the frozen final factor on already-opened CSI500.

This cohort's outcomes were opened for a different candidate in round one.
It is never an independent validation or a basis for another factor revision.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
import json

import numpy as np
import polars as pl

import audit_ma_price_transfer as original
import ma_price_research as base
import ma_price_round4 as final_round
from audit_ma_dense_days import block_interval
from ma_clean_research import measure


ROOT = base.ROOT
LOCK = ROOT / "reports/ma_price/final_candidate_lock.json"
RESULT = ROOT / "reports/ma_price/reused_csi500_final_diagnostic.json"
FACTOR = "close_lower_half"
COST = 0.003


def evaluate(frame: pl.DataFrame, schedule: dict[date, date],
             start: date, end: date, seed: int) -> dict:
    valid = {day for day, exit_day in schedule.items()
             if start <= day <= end and exit_day <= end}
    period = frame.filter(pl.col("day").is_in(valid))
    summary = measure(period, FACTOR, (start, end))
    if summary.get("days", 0) == 0:
        return {"statistics": summary, "net_cost_interval": None}
    daily = period.with_columns(
        ((pl.col(FACTOR) > 0) &
         (pl.col(FACTOR).rank("ordinal", descending=True).over("day") <= 20)).alias("selected")
    ).group_by("day").agg(
        pl.col("intent_return").filter(pl.col("selected")).mean().alias("mean"),
        pl.col("intent_return").mean().alias("baseline"),
    ).sort("day")
    by_day = {row["day"]: row for row in daily.iter_rows(named=True)}
    days = sorted(valid)
    own = np.array([by_day[d]["mean"] if d in by_day else np.nan for d in days], dtype=float)
    edge = np.array([by_day[d]["mean"] - by_day[d]["baseline"]
                     if d in by_day and by_day[d]["mean"] is not None else np.nan
                     for d in days], dtype=float)
    if int(np.isfinite(own).sum()) != summary["days"]:
        raise ValueError("daily count disagrees with original measure")
    if abs(float(np.nanmean(own)) - summary["signal_mean"]) > 1e-12:
        raise ValueError("daily mean disagrees with original measure")
    own_ci = block_interval(own, 4, seed)
    edge_ci = block_interval(edge, 4, seed + 1000)
    return {
        "scheduled_evaluable_dates": len(days),
        "statistics": summary,
        "net_cost_interval": [float(value - COST) for value in own_ci],
        "edge_interval": edge_ci,
    }


def main() -> None:
    if RESULT.exists():
        raise FileExistsError("preserve this single-use diagnostic")
    locked = json.loads(LOCK.read_text())
    if locked["selected_factor"] != FACTOR:
        raise ValueError("factor differs from prior final lock")
    if locked["source_sha256"]["round4_code"] != base.file_hash(Path(final_round.__file__)):
        raise ValueError("frozen factor code changed")
    if locked["source_sha256"]["round4_results"] != base.file_hash(
        ROOT / "reports/ma_price/round_04.json"):
        raise ValueError("selection results changed")
    existing = json.loads((ROOT / "reports/ma_price/transfer_result.json").read_text())
    frame, metadata, schedule = original.build_frame()
    scores = final_round.score_round_four(original.HOLDOUT).select(
        "day", "vt_symbol", FACTOR)
    frame = frame.join(scores, on=["day", "vt_symbol"], validate="1:1")
    if frame[FACTOR].null_count():
        raise ValueError("final scores missing on eligible CSI500 rows")
    periods = {
        "2024": evaluate(frame, schedule, date(2024, 1, 1), date(2024, 12, 31), 20260924),
        "2025": evaluate(frame, schedule, date(2025, 1, 1), date(2025, 12, 31), 20260925),
        "2026": evaluate(frame, schedule, date(2026, 1, 1), original.LAST, 20260926),
        "combined": evaluate(frame, schedule, date(2024, 1, 1), original.LAST, 20260927),
    }
    result = {
        "factor": FACTOR,
        "status": "retrospective diagnostic after prior CSI500 outcome view; not an independent test",
        "selection_contaminated_by_prior_view_of_this_pool": True,
        "no_factor_revision_allowed": True,
        "final_candidate_lock_sha256": base.file_hash(LOCK),
        "earlier_csi500_result_sha256": base.file_hash(ROOT / "reports/ma_price/transfer_result.json"),
        "bars_sha256": existing["bars_sha256"],
        "evaluation_script_sha256": base.file_hash(Path(__file__)),
        "metadata": metadata, "periods": periods,
    }
    base.safe_write(RESULT, result)
    for era, value in periods.items():
        stats = value["statistics"]
        print(era, "days", stats.get("days"), "positions", stats.get("signals"),
              "mean_pct", round((stats.get("signal_mean") or 0) * 100, 3),
              "up_pct", round((stats.get("signal_up_rate") or 0) * 100, 1),
              "net_ci_pct", ([round(x * 100, 3) for x in value["net_cost_interval"]]
                              if value["net_cost_interval"] else None))


if __name__ == "__main__":
    main()
