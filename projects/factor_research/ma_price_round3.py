"""Round 3: isolate gap, MA alignment, joint widening, and price/volume context.

The prior CSI500 transfer data are excluded from selection. Every CSI300 date
in this round was already viewed, so these are historical comparisons only.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import json

import polars as pl

import ma_price_research as base
from ma_clean_research import measure


ROOT, DATA, OUT = base.ROOT, base.DATA, base.OUT
NAMES = {
    "gap_up_only": "positive open / previous adjusted close - 1, without MA condition",
    "aligned_gap_up": "positive gap with MA5>MA20>MA60>MA120",
    "widen_gap_up_control": "round-two control: positive gap times joint widening",
    "aligned_gap_up_no_widen": "positive gap with aligned MAs but without positive joint widening",
    "widen_gap_up_green": "joint widening times positive gap times positive intraday body / ATR14",
    "widen_gap_up_red": "joint widening times positive gap times negative intraday body / ATR14",
    "widen_gap_up_volume_up": "joint widening times positive gap times positive(volume / mean20 - 1)",
    "widen_gap_up_volume_down": "joint widening times positive gap times positive(1 - volume / mean20)",
    "widen_gap_up_breakout": "joint widening times positive gap if close > previous 20-bar high",
    "widen_gap_up_inside": "joint widening times positive gap if close <= previous 20-bar high",
    "widen_gap_up_small": "joint widening times positive gap if open-previous close <= 0.5 ATR14",
    "widen_gap_up_large": "joint widening times positive gap if open-previous close > 0.5 ATR14",
}


def plan(data: Path) -> dict:
    if not 10 <= len(NAMES) <= 20:
        raise ValueError("each round requires 10-20 candidates")
    inputs = ("bars_qfq.parquet", "trade_calendar.parquet", "membership_signal_days.parquet")
    return {
        "study": "round three of user-authorized MA+price/volume study",
        "clue": "isolate positive opening gap from MA alignment and joint widening, then compare paired conditions",
        "candidate_count": len(NAMES), "candidate_formulas": NAMES,
        "control_is_previously_seen": "widen_gap_up_control",
        "data_and_return_rules": "identical to round one; historical CSI300 exploration only",
        "periods": {key: [str(a), str(b)] for key, (a, b) in base.PERIODS.items()},
        "primary": "own five-day mean return and up rate; 0.3% cost sensitivity",
        "auxiliary": "same-day cohort edge and rank IC; not vetoes",
        "historical_screen": "three eras each >=20 signal dates, >=200 positions, own mean >0.3%",
        "csi500_used_for_round_three_selection": False,
        "all_dates_previously_viewed": True,
        "script_sha256": base.file_hash(Path(__file__)),
        "round_one_code_sha256": base.file_hash(Path(base.__file__)),
        "round_two_code_sha256": base.file_hash(Path(__file__).with_name("ma_price_round2.py")),
        "round_two_result_sha256": base.file_hash(OUT / "round_02.json"),
        "failed_transfer_result_sha256": base.file_hash(OUT / "transfer_result.json"),
        "data_sha256": {name: base.file_hash(data / name) for name in inputs},
    }


def score_round_three(data: Path) -> pl.DataFrame:
    features = base.stock_features(data)
    old = base.score_round_one(features).select(
        "day", "vt_symbol", pl.col("ribbon_joint_widening").alias("widen"))
    activity = pl.read_parquet(data / "bars_qfq.parquet").select(
        pl.col("date").str.to_date().alias("day"), pl.col("code").alias("vt_symbol"),
        "volume", "close",
    ).sort(["vt_symbol", "day"]).with_columns(
        pl.col("volume").rolling_mean(20).over("vt_symbol").alias("volume_mean20"),
        pl.col("close").shift(1).over("vt_symbol").alias("previous_close"),
    ).select("day", "vt_symbol", "volume", "volume_mean20", "previous_close")
    x = features.join(old, on=["day", "vt_symbol"], validate="1:1")
    x = x.join(activity, on=["day", "vt_symbol"], validate="1:1")
    positive = lambda value: pl.max_horizontal(value, pl.lit(0.0))
    gap = pl.when(pl.col("previous_close") > 0).then(
        pl.col("open") / pl.col("previous_close") - 1)
    up = positive(gap)
    aligned = ((pl.col("g5_20") > 0) & (pl.col("g20_60") > 0)
               & (pl.col("g60_120") > 0))
    widen = pl.col("widen")
    joint = widen * up
    body = pl.when(pl.col("atr14") > 0).then(
        (pl.col("close") - pl.col("open")) / pl.col("atr14"))
    volume_ratio = pl.when(pl.col("volume_mean20") > 0).then(
        pl.col("volume") / pl.col("volume_mean20"))
    gap_atr = pl.when(pl.col("atr14") > 0).then(
        (pl.col("open") - pl.col("previous_close")) / pl.col("atr14"))
    q = x.with_columns(
        up.alias("gap_up_only"),
        pl.when(aligned).then(up).otherwise(0.0).alias("aligned_gap_up"),
        joint.alias("widen_gap_up_control"),
        pl.when(aligned & (widen <= 0)).then(up).otherwise(0.0)
        .alias("aligned_gap_up_no_widen"),
        (joint * positive(body)).alias("widen_gap_up_green"),
        (joint * positive(-body)).alias("widen_gap_up_red"),
        (joint * positive(volume_ratio - 1)).alias("widen_gap_up_volume_up"),
        (joint * positive(1 - volume_ratio)).alias("widen_gap_up_volume_down"),
        pl.when(pl.col("close") > pl.col("high20_prev")).then(joint).otherwise(0.0)
        .alias("widen_gap_up_breakout"),
        pl.when(pl.col("close") <= pl.col("high20_prev")).then(joint).otherwise(0.0)
        .alias("widen_gap_up_inside"),
        pl.when((gap_atr > 0) & (gap_atr <= 0.5)).then(joint).otherwise(0.0)
        .alias("widen_gap_up_small"),
        pl.when(gap_atr > 0.5).then(joint).otherwise(0.0)
        .alias("widen_gap_up_large"),
    )
    return q.with_columns([
        pl.when(pl.col(name).is_finite() & (pl.col(name) > 0))
        .then(pl.col(name)).otherwise(0.0).alias(name) for name in NAMES
    ]).select("day", "vt_symbol", *NAMES)


def run(data: Path, out: Path) -> None:
    plan_path = out / "round_03_plan.json"
    result_path = out / "round_03.json"
    if result_path.exists():
        raise FileExistsError("preserve old round-three results")
    if not plan_path.exists():
        raise FileNotFoundError("write round-three plan first")
    if json.loads(plan_path.read_text()) != plan(data):
        raise RuntimeError("code, selection history, or data changed after planning")
    old_frame, metadata = base.make_frame(data, 1)
    scores = score_round_three(data)
    scores = scores.filter(pl.col("day").is_in(old_frame["day"].unique().to_list()))
    frame = old_frame.select("day", "exit_day", "vt_symbol", "intent_return",
                             "worst_case_return", "entry_fill", "unclosed_at_horizon")
    frame = frame.join(scores, on=["day", "vt_symbol"], how="left", validate="1:1")
    if any(frame[name].null_count() for name in NAMES):
        raise ValueError("round-three scores missing for eligible rows")
    results = []
    for name in NAMES:
        item = {"name": name}
        for era, (start, end) in base.PERIODS.items():
            item[era] = measure(frame.filter(pl.col("exit_day") <= end), name, (start, end))
        item["historical_screen"] = base.historical_screen(item)
        results.append(item)
    output = {
        "round": 3, "plan_sha256": base.file_hash(plan_path),
        "candidate_count": len(results),
        "historical_screen_count": sum(x["historical_screen"] for x in results),
        "independent_time_test_available": False, "metadata": metadata, "results": results,
    }
    base.safe_write(result_path, output)
    print(json.dumps({"round": 3, "candidates": len(results),
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
        base.safe_write(args.out / "round_03_plan.json", plan(args.data))
        print(f"planned round three: {len(NAMES)} candidates")
    else:
        run(args.data, args.out)


if __name__ == "__main__":
    main()
