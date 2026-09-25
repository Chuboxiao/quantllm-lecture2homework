"""Final round: paired conditions on MA widening plus positive opening gap.

Selection remains confined to previously viewed CSI300 historical dates.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import json

import polars as pl

import ma_price_research as base
import ma_price_round3 as previous
from ma_clean_research import measure


DATA, OUT = base.DATA, base.OUT
NAMES = {
    "control_widen_gap": "prior joint-widening * positive opening-gap control",
    "no_chase": "control; close <= MA5 + 0.5 ATR14",
    "chase": "control; close > MA5 + 0.5 ATR14",
    "red_no_chase": "control; negative close-open and no chase",
    "red_chase": "control; negative close-open and chase",
    "red_inside": "control; negative close-open and close <= prior 20-bar high",
    "red_breakout": "control; negative close-open and close > prior 20-bar high",
    "volume_up_inside": "control; volume > 20-bar average and close <= prior 20-bar high",
    "volume_up_breakout": "control; volume > 20-bar average and close > prior 20-bar high",
    "red_volume_up": "control; negative close-open and volume > 20-bar average",
    "red_volume_down": "control; negative close-open and volume <= 20-bar average",
    "close_lower_half": "control; close in lower half of same-day high-low range",
    "close_upper_half": "control; close in upper half of same-day high-low range",
    "moderate_volume": "control; 0.8 <= volume / 20-bar average <= 1.5",
    "extreme_volume": "control; volume / 20-bar average > 1.5",
}


def plan(data: Path) -> dict:
    if not 10 <= len(NAMES) <= 20:
        raise ValueError("each round requires 10-20 candidates")
    inputs = ("bars_qfq.parquet", "trade_calendar.parquet", "membership_signal_days.parquet")
    return {
        "study": "final fourth round of user-authorized MA+price/volume study",
        "clue": "paired and reverse conditions on MA joint widening plus positive opening gap",
        "candidate_count": len(NAMES), "candidate_formulas": NAMES,
        "control_is_previously_seen": "control_widen_gap",
        "data_and_return_rules": "identical to round one; historical CSI300 exploration only",
        "periods": {key: [str(a), str(b)] for key, (a, b) in base.PERIODS.items()},
        "primary": "own five-day mean return and up rate; 0.3% cost sensitivity",
        "auxiliary": "same-day cohort edge and rank IC; not vetoes",
        "historical_screen": "three eras each >=20 signal dates, >=200 positions, own mean >0.3%",
        "csi500_used_for_round_four_selection": False,
        "all_dates_previously_viewed": True,
        "maximum_rounds_reached_after_this_run": True,
        "script_sha256": base.file_hash(Path(__file__)),
        "round_one_code_sha256": base.file_hash(Path(base.__file__)),
        "round_three_code_sha256": base.file_hash(Path(previous.__file__)),
        "round_three_result_sha256": base.file_hash(OUT / "round_03.json"),
        "round_three_diagnostic_sha256": base.file_hash(OUT / "round_03_diagnostic.json"),
        "data_sha256": {name: base.file_hash(data / name) for name in inputs},
    }


def score_round_four(data: Path) -> pl.DataFrame:
    features = base.stock_features(data).select(
        "day", "vt_symbol", "open", "high", "low", "close", "ma5", "atr14", "high20_prev")
    prior = previous.score_round_three(data).select(
        "day", "vt_symbol", pl.col("widen_gap_up_control").alias("control"))
    activity = pl.read_parquet(data / "bars_qfq.parquet").select(
        pl.col("date").str.to_date().alias("day"), pl.col("code").alias("vt_symbol"),
        "volume",
    ).sort(["vt_symbol", "day"]).with_columns(
        pl.col("volume").rolling_mean(20).over("vt_symbol").alias("volume_mean20"),
    ).select("day", "vt_symbol", "volume", "volume_mean20")
    x = features.join(prior, on=["day", "vt_symbol"], validate="1:1")
    x = x.join(activity, on=["day", "vt_symbol"], validate="1:1")
    control = pl.col("control")
    red = pl.col("close") < pl.col("open")
    no_chase = pl.col("close") <= pl.col("ma5") + 0.5 * pl.col("atr14")
    inside = pl.col("close") <= pl.col("high20_prev")
    volume_ratio = pl.when(pl.col("volume_mean20") > 0).then(
        pl.col("volume") / pl.col("volume_mean20"))
    volume_up = volume_ratio > 1
    location = pl.when(pl.col("high") > pl.col("low")).then(
        (pl.col("close") - pl.col("low")) / (pl.col("high") - pl.col("low")))
    gates = {
        "control_widen_gap": pl.lit(True),
        "no_chase": no_chase,
        "chase": ~no_chase,
        "red_no_chase": red & no_chase,
        "red_chase": red & ~no_chase,
        "red_inside": red & inside,
        "red_breakout": red & ~inside,
        "volume_up_inside": volume_up & inside,
        "volume_up_breakout": volume_up & ~inside,
        "red_volume_up": red & volume_up,
        "red_volume_down": red & (volume_ratio <= 1),
        "close_lower_half": location < 0.5,
        "close_upper_half": location >= 0.5,
        "moderate_volume": volume_ratio.is_between(0.8, 1.5),
        "extreme_volume": volume_ratio > 1.5,
    }
    q = x.with_columns([
        pl.when(gate).then(control).otherwise(0.0).alias(name)
        for name, gate in gates.items()
    ])
    return q.with_columns([
        pl.when(pl.col(name).is_finite() & (pl.col(name) > 0))
        .then(pl.col(name)).otherwise(0.0).alias(name) for name in NAMES
    ]).select("day", "vt_symbol", *NAMES)


def run(data: Path, out: Path) -> None:
    plan_path = out / "round_04_plan.json"
    result_path = out / "round_04.json"
    if result_path.exists():
        raise FileExistsError("preserve old round-four results")
    if not plan_path.exists():
        raise FileNotFoundError("write round-four plan first")
    if json.loads(plan_path.read_text()) != plan(data):
        raise RuntimeError("code, selection history, or data changed after planning")
    old_frame, metadata = base.make_frame(data, 1)
    scores = score_round_four(data)
    scores = scores.filter(pl.col("day").is_in(old_frame["day"].unique().to_list()))
    frame = old_frame.select("day", "exit_day", "vt_symbol", "intent_return",
                             "worst_case_return", "entry_fill", "unclosed_at_horizon")
    frame = frame.join(scores, on=["day", "vt_symbol"], how="left", validate="1:1")
    if any(frame[name].null_count() for name in NAMES):
        raise ValueError("round-four scores missing for eligible rows")
    results = []
    for name in NAMES:
        item = {"name": name}
        for era, (start, end) in base.PERIODS.items():
            item[era] = measure(frame.filter(pl.col("exit_day") <= end), name, (start, end))
        item["historical_screen"] = base.historical_screen(item)
        results.append(item)
    output = {
        "round": 4, "plan_sha256": base.file_hash(plan_path),
        "candidate_count": len(results),
        "historical_screen_count": sum(x["historical_screen"] for x in results),
        "independent_time_test_available": False, "metadata": metadata, "results": results,
    }
    base.safe_write(result_path, output)
    print(json.dumps({"round": 4, "candidates": len(results),
                      "screen_count": output["historical_screen_count"]}, ensure_ascii=False))
    for item in results:
        own = [round(item[p].get("signal_mean", 0) * 100, 3) for p in base.PERIODS]
        edge = [round(item[p].get("edge", 0) * 100, 3) for p in base.PERIODS]
        print(item["name"], "own_pct", own, "edge_pp", edge,
              "screen", item["historical_screen"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("plan", "run"), required=True)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    if args.stage == "plan":
        base.safe_write(args.out / "round_04_plan.json", plan(args.data))
        print(f"planned round four: {len(NAMES)} candidates")
    else:
        run(args.data, args.out)


if __name__ == "__main__":
    main()
