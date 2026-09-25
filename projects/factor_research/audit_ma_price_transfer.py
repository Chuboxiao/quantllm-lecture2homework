"""One locked CSI500 transfer check of the round-one MA widening score.

This is a different fixed stock universe on previously observed calendar years,
not an independent future-time test or a claim of executable profits.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
import json

import numpy as np
import polars as pl

import ma_clean_research as old
from audit_ma_dense_days import block_interval
from ma_price_research import DATA as CSI300_DATA, ROOT, file_hash, safe_write, score_round_one, stock_features


HOLDOUT = ROOT / "data/factor_research/csi500_2023_fixed"
LOCK = ROOT / "reports/ma_price/transfer_lock.json"
RESULT = ROOT / "reports/ma_price/transfer_result.json"
FACTOR = "ribbon_joint_widening"
LAST = date(2026, 9, 23)
COST = 0.003


def scheduled_dates() -> dict[date, date]:
    calendar = pl.read_parquet(CSI300_DATA / "trade_calendar.parquet")
    days = [date.fromisoformat(value) for value, active in calendar.iter_rows() if active == 1]
    return {days[i]: days[i + 6] for i in range(0, len(days) - 6, 6)
            if date(2024, 1, 1) <= days[i] and days[i + 6] <= LAST}


def build_frame() -> tuple[pl.DataFrame, dict, dict[date, date]]:
    members = json.loads((HOLDOUT / "members.json").read_text())
    allowed = set(members["codes"])
    if len(allowed) != 500 or members["requested_asof"] != "2023-12-29":
        raise ValueError("unexpected locked cohort")
    bars = pl.read_parquet(HOLDOUT / "bars_qfq.parquet")
    if set(bars["code"].unique().to_list()) != allowed:
        raise ValueError("downloaded symbols differ from locked cohort")
    raw = bars.with_columns(pl.col("date").str.to_date().alias("day"),
                            pl.col("code").alias("vt_symbol"))
    previous_step = old.STEP
    try:
        old.STEP = 1
        base, metadata = old.make_frame(raw, 2, "fresh", date(2024, 1, 1), LAST)
    finally:
        old.STEP = previous_step
    features = stock_features(HOLDOUT)
    scored = score_round_one(features).select("day", "vt_symbol", FACTOR)
    ma120 = features.select("day", "vt_symbol", "ma120")
    fixed = base.select("day", "exit_day", "vt_symbol", "intent_return", "worst_case_return",
                        "entry_fill", "unclosed_at_horizon")
    fixed = fixed.join(scored, on=["day", "vt_symbol"], how="left", validate="1:1")
    fixed = fixed.join(ma120, on=["day", "vt_symbol"], how="left", validate="1:1")
    fixed = fixed.filter(pl.col("ma120").is_finite())
    schedule = scheduled_dates()
    fixed = fixed.filter(pl.col("day").is_in(list(schedule)))
    if fixed.is_empty() or fixed[FACTOR].null_count():
        raise ValueError("transfer scoring failed")
    if any(schedule[day] != exit_day for day, exit_day in
           fixed.select("day", "exit_day").unique().iter_rows()):
        raise ValueError("signal dates or exit dates differ from locked market calendar")
    metadata["scheduled_dates"] = len(schedule)
    metadata["transfer_eligible_rows"] = fixed.height
    metadata["transfer_signal_dates_with_eligible"] = fixed["day"].n_unique()
    return fixed, metadata, schedule


def daily_statistics(frame: pl.DataFrame) -> pl.DataFrame:
    x = frame.with_columns(
        ((pl.col(FACTOR) > 0) &
         (pl.col(FACTOR).rank("ordinal", descending=True).over("day") <= 20)).alias("selected")
    )
    return x.group_by("day").agg(
        pl.col("selected").sum().alias("selected_stocks"),
        pl.col("intent_return").mean().alias("baseline_mean"),
        pl.col("intent_return").filter(pl.col("selected")).mean().alias("signal_mean"),
    ).with_columns((pl.col("signal_mean") - pl.col("baseline_mean")).alias("edge"))


def evaluate(frame: pl.DataFrame, schedule: dict[date, date], start: date, end: date, seed: int) -> dict:
    valid = {day for day, exit_day in schedule.items() if start <= day <= end and exit_day <= end}
    period = frame.filter(pl.col("day").is_in(valid))
    measured = old.measure(period, FACTOR, (start, end))
    if measured.get("days", 0) == 0:
        raise ValueError("no triggered transfer dates")
    by_day = {row["day"]: row for row in daily_statistics(period).iter_rows(named=True)}
    dates = sorted(valid)
    own = np.array([by_day[d]["signal_mean"] if d in by_day else np.nan for d in dates], dtype=float)
    edge = np.array([by_day[d]["edge"] if d in by_day else np.nan for d in dates], dtype=float)
    if int(np.isfinite(own).sum()) != measured["days"]:
        raise ValueError("daily signal count disagrees with original measure")
    if abs(float(np.nanmean(own)) - measured["signal_mean"]) > 1e-12:
        raise ValueError("daily and original means disagree")
    own_interval = block_interval(own, 4, seed)
    edge_interval = block_interval(edge, 4, seed + 1000)
    return {
        "scheduled_evaluable_dates": len(dates), "statistics": measured,
        "block4_mean_95pct": own_interval,
        "block4_after_0p3pct_cost_95pct": [value - COST for value in own_interval],
        "block4_edge_95pct": edge_interval,
    }


def main() -> None:
    if RESULT.exists():
        raise FileExistsError("transfer evidence is single-use")
    lock = json.loads(LOCK.read_text())
    if lock["chosen_factor"] != FACTOR or not lock["locked_before_csi500_bars"]:
        raise ValueError("missing pre-data selection lock")
    if lock["membership_sha256"] != file_hash(HOLDOUT / "members.json"):
        raise ValueError("member list changed after lock")
    if lock["round_01_result_sha256"] != file_hash(ROOT / "reports/ma_price/round_01.json"):
        raise ValueError("selection data changed after lock")
    manifest = json.loads((HOLDOUT / "manifest.json").read_text())
    if manifest["bars_sha256"] != file_hash(HOLDOUT / "bars_qfq.parquet"):
        raise ValueError("bar data differs from download manifest")
    frame, metadata, schedule = build_frame()
    periods = {
        "2024": evaluate(frame, schedule, date(2024, 1, 1), date(2024, 12, 31), 20260924),
        "2025": evaluate(frame, schedule, date(2025, 1, 1), date(2025, 12, 31), 20260925),
        "2026": evaluate(frame, schedule, date(2026, 1, 1), LAST, 20260926),
        "combined": evaluate(frame, schedule, date(2024, 1, 1), LAST, 20260927),
    }
    combined = periods["combined"]
    aggregate = combined["statistics"]
    support = (
        aggregate["days"] >= 50 and aggregate["signals"] >= 500
        and periods["2024"]["statistics"]["signal_mean"] > COST
        and periods["2025"]["statistics"]["signal_mean"] > COST
        and combined["block4_after_0p3pct_cost_95pct"][0] > 0
        and aggregate["edge"] > 0
    )
    safe_write(RESULT, {
        "factor": FACTOR, "transfer_support_by_locked_rule": support,
        "not_an_independent_time_test": True,
        "lock_sha256": file_hash(LOCK), "bars_sha256": manifest["bars_sha256"],
        "evaluation_script_sha256": file_hash(Path(__file__)),
        "metadata": metadata, "periods": periods,
    })
    print(json.dumps({"transfer_support": support, "periods": {
        key: {"days": value["statistics"]["days"],
              "signals": value["statistics"]["signals"],
              "mean": value["statistics"]["signal_mean"],
              "edge": value["statistics"]["edge"],
              "net_95pct": value["block4_after_0p3pct_cost_95pct"]}
        for key, value in periods.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
