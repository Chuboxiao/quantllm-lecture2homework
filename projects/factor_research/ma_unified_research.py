"""Exploratory MA-factor replication on one BaoStock historical stock dataset.

Every date in this dataset has already been seen in earlier research. This script
does not create an independent holdout or a tradable backtest.
"""
from __future__ import annotations

from datetime import date
from hashlib import sha256
from pathlib import Path
import argparse
import json
import math

import polars as pl

from ma_clean_research import add_features, measure


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/factor_research/baostock_csi300_history"
OUT = ROOT / "reports/ma_unified"
PERIODS = {
    "2008_2012": (date(2008, 1, 2), date(2012, 12, 31)),
    "2013_2017": (date(2013, 1, 1), date(2017, 12, 31)),
    "2018_2022": (date(2018, 1, 1), date(2022, 12, 31)),
    "2023_2026": (date(2023, 1, 1), date(2026, 9, 23)),
}
FACTORS = {
    "ma20_over_60": "max(MA20/MA60-1, 0): medium trend",
    "ma60_over_120": "max(MA60/MA120-1, 0): slower trend",
    "ma5_over_20": "max(MA5/MA20-1, 0): short trend",
    "price_over_ma20": "max(close/MA20-1, 0): price above medium trend",
    "ma20_slope_5": "max(MA20/MA20[5 bars ago]-1, 0): medium slope",
    "ma60_slope_10": "max(MA60/MA60[10 bars ago]-1, 0): slow slope",
    "ma5_20_accel_5": "max((MA5/MA20-1)-its 5-bar lag, 0): short acceleration",
    "trend_persistence_20": "if MA20>MA60 and >50% of last 20 closes exceed MA20, score that fraction",
    "uptrend_pullback": "if MA20>MA60 and MA20<close<MA5, score MA5/close-1",
    "uptrend_reclaim_ma5": "if MA20>MA60 and close crosses above MA5, score long gap + close/MA5-1",
    "bear_trend_rebound": "if MA20<MA60 and close>MA5, score -long gap + close/MA5-1",
    "old_market_down_pullback": "old diagnostic: uptrend pullback when same-day cohort mean return <0; score long gap+pullback",
}
STEP = 6
COST = 0.003


def file_hash(path: Path) -> str:
    h = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def specification(data: Path) -> dict:
    filenames = ["bars_qfq.parquet", "trade_calendar.parquet", "membership_signal_days.parquet"]
    missing = [name for name in filenames if not (data / name).exists()]
    if missing:
        raise FileNotFoundError(f"required data absent: {missing}")
    return {
        "study": "new unified-source exploratory replication, not a fifth round of the old locked study",
        "clue": "Do moving-average trend, slope, persistence or pullback scores predict the stock's own five-day rise?",
        "candidate_count": len(FACTORS), "candidate_formulas": FACTORS,
        "signal": "t close; every 6th market trading day starting 2008-01-02; exact as-of CSI300 membership",
        "target": "t+1 open to t+6 open; no entry fill=0; no horizon exit=latest close mark plus -100% stress",
        "selection": "top 20 positive-score eligible stocks per day; no future-based eligibility exclusions",
        "eligible": "t close>0, volume>0, tradestatus=1, isST=0, finite MA120 and input features",
        "evaluations": "own average return and up-rate primary; same-day cohort edge and Rank IC auxiliary",
        "cost_sensitivity": "0.3% illustrative round trip, not measured execution cost",
        "periods": {key: [str(a), str(b)] for key, (a, b) in PERIODS.items()},
        "consistency_rule": "all four eras each >=40 signal days and >=400 selected stocks, own mean >0.3%, cohort edge >0.15 percentage points, mean Rank IC >0.01",
        "all_periods_previously_viewed": True,
        "independent_test_available": False,
        "script_sha256": file_hash(Path(__file__)),
        "data_sha256": {name: file_hash(data / name) for name in filenames},
    }


def scored_features(x: pl.DataFrame) -> pl.DataFrame:
    x = x.with_columns(
        (pl.col("ma60") / pl.col("ma120") - 1).alias("slow_gap"),
        (pl.col("ma60") / pl.col("ma60_lag10") - 1).alias("slow_slope"),
        (pl.col("short_gap") - pl.col("short_gap_lag5")).alias("short_accel"),
    )
    gap = pl.col("long_gap")
    depth = pl.col("depth5")
    uptrend_pullback = (gap > 0) & (pl.col("close") > pl.col("ma20")) & (depth > 0)
    positive = lambda value: pl.when(value > 0).then(value).otherwise(0.0)
    gated = lambda condition, value: pl.when(condition).then(value).otherwise(0.0)
    return x.with_columns(
        positive(gap).alias("ma20_over_60"),
        positive(pl.col("slow_gap")).alias("ma60_over_120"),
        positive(pl.col("short_gap")).alias("ma5_over_20"),
        positive(pl.col("close") / pl.col("ma20") - 1).alias("price_over_ma20"),
        positive(pl.col("long_slope")).alias("ma20_slope_5"),
        positive(pl.col("slow_slope")).alias("ma60_slope_10"),
        positive(pl.col("short_accel")).alias("ma5_20_accel_5"),
        gated((gap > 0) & (pl.col("above_ma20_fraction20") > 0.5),
              pl.col("above_ma20_fraction20")).alias("trend_persistence_20"),
        gated(uptrend_pullback, depth).alias("uptrend_pullback"),
        gated((gap > 0) & (pl.col("close") > pl.col("ma5"))
              & (pl.col("previous_close") <= pl.col("ma5_lag1")),
              gap + pl.col("close") / pl.col("ma5") - 1).alias("uptrend_reclaim_ma5"),
        gated((gap < 0) & (pl.col("close") > pl.col("ma5")),
              -gap + pl.col("close") / pl.col("ma5") - 1).alias("bear_trend_rebound"),
        gated(uptrend_pullback & (pl.col("market_day_return") < 0),
              gap + depth).alias("old_market_down_pullback"),
    )


def make_frame(data: Path) -> tuple[pl.DataFrame, dict]:
    calendar = pl.read_parquet(data / "trade_calendar.parquet")
    market_days = [date.fromisoformat(day) for day, active in calendar.iter_rows() if active == 1]
    signals = pl.DataFrame({
        "day": market_days[:-6:STEP],
        "entry_day": market_days[1:-5:STEP],
        "exit_day": market_days[6::STEP],
    })
    members = pl.read_parquet(data / "membership_signal_days.parquet").select(
        pl.col("asof_date").str.to_date().alias("day"),
        pl.col("code").alias("vt_symbol"),
    )
    if members.height != signals.height * 300 or members.unique(["day", "vt_symbol"]).height != members.height:
        raise ValueError("exact signal-date membership is incomplete or duplicated")
    if members["day"].unique().sort().to_list() != signals["day"].to_list():
        raise ValueError("exact membership dates do not match the sampling calendar")
    bars = pl.read_parquet(data / "bars_qfq.parquet").select(
        pl.col("date").str.to_date().alias("day"),
        pl.col("code").alias("vt_symbol"),
        "open", "high", "low", "close", "volume", "tradestatus", "isST",
    )
    x = add_features(bars)
    x = x.with_columns(
        pl.col("close").rolling_mean(120).over("vt_symbol").alias("ma120"),
        pl.col("ma60").shift(10).over("vt_symbol").alias("ma60_lag10"),
        pl.col("short_gap").shift(5).over("vt_symbol").alias("short_gap_lag5"),
        (pl.col("close") > pl.col("ma20")).cast(pl.Float64)
        .rolling_mean(20).over("vt_symbol").alias("above_ma20_fraction20"),
    )
    active = members.join(signals, on="day").join(x, on=["day", "vt_symbol"], how="left")
    potential = active.height
    active = active.filter(
        (pl.col("close") > 0) & (pl.col("volume") > 0)
        & (pl.col("tradestatus") == 1) & (pl.col("isST") == 0)
        & pl.col("ma120").is_finite() & pl.col("long_gap").is_finite()
        & pl.col("depth5").is_finite()
    )
    active = active.with_columns(pl.col("day_return").mean().over("day").alias("market_day_return"))
    active = scored_features(active)
    future_bars = bars.select("vt_symbol", "day", "open", "close", "volume", "tradestatus")
    active = active.join(
        future_bars.select("vt_symbol", pl.col("day").alias("entry_day"),
                           pl.col("open").alias("entry_open"),
                           pl.col("volume").alias("entry_volume"),
                           pl.col("tradestatus").alias("entry_status")),
        on=["vt_symbol", "entry_day"], how="left",
    ).join(
        future_bars.select("vt_symbol", pl.col("day").alias("exit_day"),
                           pl.col("open").alias("exit_open"),
                           pl.col("volume").alias("exit_volume"),
                           pl.col("tradestatus").alias("exit_status")),
        on=["vt_symbol", "exit_day"], how="left",
    )
    marks = future_bars.select("vt_symbol", pl.col("day").alias("mark_day"),
                               pl.col("close").alias("mark_close"))
    active = active.sort("exit_day").join_asof(
        marks.sort("mark_day"), left_on="exit_day", right_on="mark_day",
        by="vt_symbol", strategy="backward",
    )
    active = active.with_columns(
        ((pl.col("entry_open") > 0) & (pl.col("entry_volume") > 0)
         & (pl.col("entry_status") == 1)).fill_null(False).alias("entry_fill"),
        ((pl.col("exit_open") > 0) & (pl.col("exit_volume") > 0)
         & (pl.col("exit_status") == 1)).fill_null(False).alias("exit_fill"),
    )
    active = active.with_columns(
        pl.when(~pl.col("entry_fill")).then(0.0)
        .when(~pl.col("exit_fill")).then(pl.col("mark_close") / pl.col("entry_open") - 1)
        .otherwise(pl.col("exit_open") / pl.col("entry_open") - 1).alias("intent_return"),
        pl.when(~pl.col("entry_fill")).then(0.0)
        .when(~pl.col("exit_fill")).then(-1.0)
        .otherwise(pl.col("exit_open") / pl.col("entry_open") - 1).alias("worst_case_return"),
        (pl.col("entry_fill") & ~pl.col("exit_fill")).alias("unclosed_at_horizon"),
    )
    if active["intent_return"].null_count() or not active["intent_return"].is_finite().all():
        raise ValueError("missing or non-finite intent return")
    frame = active.select("day", "exit_day", "vt_symbol", "intent_return",
                          "worst_case_return", "entry_fill", "unclosed_at_horizon",
                          *FACTORS)
    metadata = {
        "intended_member_rows": potential, "eligible_t_day_rows": frame.height,
        "signal_days_with_eligible_stocks": frame["day"].n_unique(),
        "entry_no_fill_all_eligible": frame.filter(~pl.col("entry_fill")).height,
        "unclosed_at_horizon_all_eligible": frame.filter(pl.col("unclosed_at_horizon")).height,
    }
    return frame, metadata


def consistent(result: dict) -> bool:
    for era in PERIODS:
        r = result[era]
        ic = r.get("rank_ic")
        if (r.get("days", 0) < 40 or r.get("signals", 0) < 400
                or r.get("signal_mean", -1) <= COST
                or r.get("edge", -1) <= 0.0015
                or ic is None or not math.isfinite(ic) or ic <= 0.01):
            return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--stage", choices=("plan", "run"), required=True)
    args = parser.parse_args()
    spec_path = args.out / "spec.json"
    if args.stage == "plan":
        if spec_path.exists():
            raise FileExistsError("study specification already exists")
        spec = specification(args.data)
        save(spec_path, spec)
        print(f"planned {len(FACTORS)} factors; all periods exploratory")
        return
    result_path = args.out / "results.json"
    if result_path.exists():
        raise FileExistsError("preserve existing study results")
    if not spec_path.exists():
        raise FileNotFoundError("run --stage plan first")
    spec = json.loads(spec_path.read_text())
    if spec != specification(args.data):
        raise RuntimeError("specification, code or source data changed after planning")
    frame, meta = make_frame(args.data)
    results = []
    for name in FACTORS:
        item = {"name": name}
        for era, period in PERIODS.items():
            # A sample must fully exit within its era, including at the boundary.
            item[era] = measure(frame.filter(pl.col("exit_day") <= period[1]), name, period)
        item["consistent_four_eras"] = consistent(item)
        results.append(item)
    output = {"spec_sha256": file_hash(spec_path), "metadata": meta,
              "candidate_count": len(results), "consistent_four_eras": sum(x["consistent_four_eras"] for x in results),
              "independent_test_available": False, "results": results}
    save(result_path, output)
    print(json.dumps({"candidate_count": output["candidate_count"],
                      "consistent_four_eras": output["consistent_four_eras"],
                      "metadata": meta}, ensure_ascii=False))
    for item in results:
        edges = [round(item[p].get("edge", 0) * 100, 3) for p in PERIODS]
        print(item["name"], "edge_pp_by_era", edges,
              "consistent", item["consistent_four_eras"])


if __name__ == "__main__":
    main()
