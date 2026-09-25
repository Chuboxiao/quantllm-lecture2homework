"""Round 2: test whether price, volume or volatility qualifies MA widening.

The fixed CSI500 transfer cohort has already been opened and is excluded from
all round-two selection. CSI300 dates are previously viewed exploration data.
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
    "widen_no_chase": "joint MA widening; close no more than 0.5 ATR14 above MA5",
    "widen_upper_range": "joint MA widening; close in top 30% of recent 20-bar range",
    "widen_breakout20": "joint MA widening; close above prior 20-bar high",
    "widen_inside_high20": "joint MA widening; close at or below prior 20-bar high",
    "widen_green_body": "joint MA widening weighted by positive same-day close-open body / ATR14",
    "widen_red_body": "joint MA widening weighted by negative same-day close-open body / ATR14",
    "widen_volume_up": "joint MA widening weighted by volume / 20-bar average above one",
    "widen_volume_down": "joint MA widening weighted by volume / 20-bar average below one",
    "widen_atr_up": "joint MA widening weighted by ATR5 / ATR20 above one",
    "widen_atr_down": "joint MA widening weighted by ATR5 / ATR20 below one",
    "widen_gap_up": "joint MA widening weighted by t-open / previous close positive gap",
    "widen_gap_down": "joint MA widening weighted by t-open / previous close negative gap",
}


def plan(data: Path) -> dict:
    if len(NAMES) < 10 or len(NAMES) > 20:
        raise ValueError("each round must contain 10-20 factors")
    inputs = ("bars_qfq.parquet", "trade_calendar.parquet", "membership_signal_days.parquet")
    return {
        "study": "round two of user-authorized MA+price/volume study",
        "clue": "synchronous widening may chase overheated prices; test price/volume/volatility conditions",
        "candidate_count": len(NAMES), "candidate_formulas": NAMES,
        "data_and_return_rules": "identical to round one; historical CSI300 exploration only",
        "periods": {key: [str(a), str(b)] for key, (a, b) in base.PERIODS.items()},
        "primary": "own five-day mean return and up rate; 0.3% cost sensitivity",
        "auxiliary": "same-day cohort edge and rank IC; not vetoes",
        "historical_screen": "three eras each >=20 signal dates, >=200 positions, own mean >0.3%",
        "csi500_used_for_round_two_selection": False,
        "all_dates_previously_viewed": True,
        "script_sha256": base.file_hash(Path(__file__)),
        "round_one_code_sha256": base.file_hash(Path(base.__file__)),
        "round_one_result_sha256": base.file_hash(OUT / "round_01.json"),
        "failed_transfer_result_sha256": base.file_hash(OUT / "transfer_result.json"),
        "data_sha256": {name: base.file_hash(data / name) for name in inputs},
    }


def score_round_two(data: Path) -> pl.DataFrame:
    features = base.stock_features(data)
    old = base.score_round_one(features).select("day", "vt_symbol",
                                                pl.col("ribbon_joint_widening").alias("widen"))
    # All rolling data are evaluated only through t. The current day's volume
    # and previous adjusted close are known at the t-close signal time.
    activity = pl.read_parquet(data / "bars_qfq.parquet").select(
        pl.col("date").str.to_date().alias("day"), pl.col("code").alias("vt_symbol"),
        "volume", "close",
    ).sort(["vt_symbol", "day"])
    activity = activity.with_columns(
        pl.col("volume").rolling_mean(20).over("vt_symbol").alias("volume_mean20"),
        pl.col("close").shift(1).over("vt_symbol").alias("previous_close"),
    ).select("day", "vt_symbol", "volume", "volume_mean20", "previous_close")
    x = features.join(old, on=["day", "vt_symbol"], validate="1:1")
    x = x.join(activity, on=["day", "vt_symbol"], validate="1:1")
    p = lambda value: pl.max_horizontal(value, pl.lit(0.0))
    b = pl.col("widen")
    safe_atr = pl.when(pl.col("atr14") > 0).then(pl.col("atr14"))
    vol_ratio = pl.when(pl.col("volume_mean20") > 0).then(
        pl.col("volume") / pl.col("volume_mean20"))
    atr_ratio = pl.when(pl.col("atr20") > 0).then(pl.col("atr5") / pl.col("atr20"))
    gap = pl.when(pl.col("previous_close") > 0).then(
        pl.col("open") / pl.col("previous_close") - 1)
    intraday = (pl.col("close") - pl.col("open")) / safe_atr
    range20 = pl.col("high20") - pl.col("low20")
    location = pl.when(range20 > 0).then((pl.col("close") - pl.col("low20")) / range20)
    q = x.with_columns(
        pl.when(pl.col("close") <= pl.col("ma5") + 0.5 * pl.col("atr14"))
        .then(b).otherwise(0.0).alias("widen_no_chase"),
        (b * p(location - 0.7)).alias("widen_upper_range"),
        pl.when(pl.col("close") > pl.col("high20_prev"))
        .then(b).otherwise(0.0).alias("widen_breakout20"),
        pl.when(pl.col("close") <= pl.col("high20_prev"))
        .then(b).otherwise(0.0).alias("widen_inside_high20"),
        (b * p(intraday)).alias("widen_green_body"),
        (b * p(-intraday)).alias("widen_red_body"),
        (b * p(vol_ratio - 1)).alias("widen_volume_up"),
        (b * p(1 - vol_ratio)).alias("widen_volume_down"),
        (b * p(atr_ratio - 1)).alias("widen_atr_up"),
        (b * p(1 - atr_ratio)).alias("widen_atr_down"),
        (b * p(gap)).alias("widen_gap_up"),
        (b * p(-gap)).alias("widen_gap_down"),
    )
    return q.with_columns([
        pl.when(pl.col(name).is_finite() & (pl.col(name) > 0))
        .then(pl.col(name)).otherwise(0.0).alias(name) for name in NAMES
    ]).select("day", "vt_symbol", *NAMES)


def run(data: Path, out: Path) -> None:
    plan_path = out / "round_02_plan.json"
    result_path = out / "round_02.json"
    if result_path.exists():
        raise FileExistsError("preserve old round-two results")
    if not plan_path.exists():
        raise FileNotFoundError("write round-two plan first")
    if json.loads(plan_path.read_text()) != plan(data):
        raise RuntimeError("code, selection history, or data changed after planning")
    old_frame, metadata = base.make_frame(data, 1)
    scores = score_round_two(data)
    scores = scores.filter(pl.col("day").is_in(old_frame["day"].unique().to_list()))
    frame = old_frame.select("day", "exit_day", "vt_symbol", "intent_return",
                             "worst_case_return", "entry_fill", "unclosed_at_horizon")
    frame = frame.join(scores, on=["day", "vt_symbol"], how="left", validate="1:1")
    if any(frame[name].null_count() for name in NAMES):
        raise ValueError("round-two scores missing for eligible rows")
    results = []
    for name in NAMES:
        item = {"name": name}
        for era, (start, end) in base.PERIODS.items():
            item[era] = measure(frame.filter(pl.col("exit_day") <= end), name, (start, end))
        item["historical_screen"] = base.historical_screen(item)
        results.append(item)
    output = {
        "round": 2, "plan_sha256": base.file_hash(plan_path),
        "candidate_count": len(results), "historical_screen_count": sum(x["historical_screen"] for x in results),
        "independent_time_test_available": False, "metadata": metadata, "results": results,
    }
    base.safe_write(result_path, output)
    print(json.dumps({"round": 2, "candidates": len(results),
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
        base.safe_write(args.out / "round_02_plan.json", plan(args.data))
        print(f"planned round two: {len(NAMES)} candidates")
    else:
        run(args.data, args.out)


if __name__ == "__main__":
    main()
