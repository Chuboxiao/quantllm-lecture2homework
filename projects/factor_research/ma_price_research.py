"""Predeclared rounds of MA + OHLCV hypotheses on historical CSI300 members.

All available dates were viewed in previous studies. Results are exploratory,
not an independent future test or an executable trading backtest.
"""
from __future__ import annotations

from datetime import date
from hashlib import sha256
from pathlib import Path
import argparse
import json

import polars as pl

from ma_clean_research import add_features, measure
from ma_unified_research import make_frame as make_old_eligible_frame


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/factor_research/baostock_csi300_history"
OUT = ROOT / "reports/ma_price"
COST = 0.003  # illustrative round trip only; not actual paid cost
PERIODS = {
    "train_2008_2016": (date(2008, 1, 2), date(2016, 12, 31)),
    "valid_2017_2022": (date(2017, 1, 1), date(2022, 12, 31)),
    "recent_2023_2026": (date(2023, 1, 1), date(2026, 9, 23)),
}

ROUND_FACTORS = {
    1: {
        "ribbon_weakest_gap": "positive minimum of MA5/20, MA20/60, MA60/120 gaps",
        "ribbon_joint_widening": "all four MAs aligned and all three gaps widen over five stock bars",
        "ribbon_compress_expand": "four MAs aligned; ribbon narrowed then widened",
        "trend_close_breakout20": "MA20>MA60>MA120; close above previous 20-bar high",
        "ribbon_range_high": "four MAs aligned; close near top of current 20-bar high-low range",
        "trend_intraday_reclaim20": "MA20>MA60>MA120; low below and close above MA20",
        "trend_peak_pullback_strong_close": "long trend, 2-8% below previous 20-bar high, strong close location",
        "ribbon_atr_contraction": "four MAs aligned; ATR5 below ATR20",
        "ribbon_atr_expansion_green": "four MAs aligned; ATR5 above ATR20 and close above open",
        "trend_intraday_reclaim5": "long trend; open below and close above MA5",
    }
}


def file_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_write(path: Path, item: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:
        json.dump(item, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def plan(round_number: int, data: Path) -> dict:
    needed = ("bars_qfq.parquet", "trade_calendar.parquet", "membership_signal_days.parquet")
    if any(not (data / name).is_file() for name in needed):
        raise FileNotFoundError("unified data or exact membership missing")
    factors = ROUND_FACTORS[round_number]
    if not 10 <= len(factors) <= 20:
        raise ValueError("each round requires 10-20 candidates")
    return {
        "study": "new MA + OHLCV exploration authorized 2026-09-24",
        "round": round_number,
        "candidate_count": len(factors),
        "candidate_formulas": factors,
        "clue": "multi-scale MA structure plus same-day price action predicts own five-day rise",
        "signal": "t close, every sixth market date since 2008-01-02, exact CSI300 membership on t",
        "target": "t+1 open to t+6 open; no entry=zero intent return; no exit=latest close mark and stress return",
        "selection": "highest 20 strictly positive scores per signal date, deterministic ordinal rank",
        "eligible": "same t-day filters and future non-fill treatment as locked unified-source study",
        "periods": {key: [str(a), str(b)] for key, (a, b) in PERIODS.items()},
        "primary": "stock's own mean five-day intent return, up rate, 0.3% cost sensitivity",
        "auxiliary": "same-day eligible-universe return edge and rank IC; neither vetoes primary",
        "historical_screen": "each of three eras: >=20 triggered dates, >=200 selected stocks, own mean >0.3%",
        "ideal_rule": "requires new unseen time-period evidence with credible positive net return; unavailable now",
        "all_current_dates_previously_viewed": True,
        "independent_time_test_available": False,
        "script_sha256": file_hash(Path(__file__)),
        "upstream_eligibility_sha256": file_hash(Path(__file__).with_name("ma_unified_research.py")),
        "data_sha256": {name: file_hash(data / name) for name in needed},
    }


def stock_features(data: Path) -> pl.DataFrame:
    bars = pl.read_parquet(data / "bars_qfq.parquet").select(
        pl.col("date").str.to_date().alias("day"), pl.col("code").alias("vt_symbol"),
        "open", "high", "low", "close", "volume", "tradestatus",
    )
    x = add_features(bars)
    x = x.with_columns(
        pl.col("close").rolling_mean(120).over("vt_symbol").alias("ma120"),
        pl.when((pl.col("high") > 0) & (pl.col("low") > 0) & (pl.col("tradestatus") == 1))
        .then(pl.col("high")).alias("valid_high"),
        pl.when((pl.col("high") > 0) & (pl.col("low") > 0) & (pl.col("tradestatus") == 1))
        .then(pl.col("low")).alias("valid_low"),
    )
    x = x.with_columns(
        (pl.col("ma5") / pl.col("ma20") - 1).alias("g5_20"),
        (pl.col("ma20") / pl.col("ma60") - 1).alias("g20_60"),
        (pl.col("ma60") / pl.col("ma120") - 1).alias("g60_120"),
        (pl.col("ma5") / pl.col("ma120") - 1).alias("ribbon_width"),
        pl.col("valid_high").shift(1).over("vt_symbol").alias("high_prev"),
        pl.col("valid_high").rolling_max(20).over("vt_symbol").alias("high20"),
        pl.col("valid_low").rolling_min(20).over("vt_symbol").alias("low20"),
        pl.when((pl.col("previous_close") > 0) & pl.col("valid_high").is_not_null())
        .then(pl.max_horizontal(
            pl.col("high") - pl.col("low"),
            (pl.col("high") - pl.col("previous_close")).abs(),
            (pl.col("low") - pl.col("previous_close")).abs(),
        )).alias("true_range"),
    )
    x = x.with_columns(
        pl.col("g5_20").shift(5).over("vt_symbol").alias("g5_20_lag5"),
        pl.col("g20_60").shift(5).over("vt_symbol").alias("g20_60_lag5"),
        pl.col("g60_120").shift(5).over("vt_symbol").alias("g60_120_lag5"),
        pl.col("ribbon_width").shift(5).over("vt_symbol").alias("width_lag5"),
        pl.col("ribbon_width").shift(10).over("vt_symbol").alias("width_lag10"),
        pl.col("high_prev").rolling_max(20).over("vt_symbol").alias("high20_prev"),
        pl.col("true_range").rolling_mean(5).over("vt_symbol").alias("atr5"),
        pl.col("true_range").rolling_mean(14).over("vt_symbol").alias("atr14"),
        pl.col("true_range").rolling_mean(20).over("vt_symbol").alias("atr20"),
    )
    # Only carry feature columns for the sampled dates into the 220k-row join.
    return x.select(
        "day", "vt_symbol", "open", "high", "low", "close", "ma5", "ma20", "ma60", "ma120",
        "g5_20", "g20_60", "g60_120", "g5_20_lag5", "g20_60_lag5", "g60_120_lag5",
        "ribbon_width", "width_lag5", "width_lag10", "high20", "low20", "high20_prev",
        "atr5", "atr14", "atr20",
    )


def score_round_one(x: pl.DataFrame) -> pl.DataFrame:
    a, b, c = pl.col("g5_20"), pl.col("g20_60"), pl.col("g60_120")
    aligned = (a > 0) & (b > 0) & (c > 0)
    trend = (b > 0) & (c > 0)
    positive = lambda value: pl.max_horizontal(value, pl.lit(0.0))
    score = lambda gate, value: pl.when(gate).then(positive(value)).otherwise(0.0)
    safe_atr = pl.when(pl.col("atr14") > 0).then(pl.col("atr14"))
    range20 = pl.col("high20") - pl.col("low20")
    location = pl.when(range20 > 0).then((pl.col("close") - pl.col("low20")) / range20)
    high_prev = pl.col("high20_prev")
    drawdown = pl.when(high_prev > 0).then(1 - pl.col("close") / high_prev)
    ratio_atr = pl.when(pl.col("atr20") > 0).then(pl.col("atr5") / pl.col("atr20"))
    raw_scores = x.with_columns(
        positive(pl.min_horizontal(a, b, c)).alias("ribbon_weakest_gap"),
        score(aligned & pl.col("g5_20_lag5").is_not_null()
              & pl.col("g20_60_lag5").is_not_null()
              & pl.col("g60_120_lag5").is_not_null(), pl.min_horizontal(
            a - pl.col("g5_20_lag5"), b - pl.col("g20_60_lag5"),
            c - pl.col("g60_120_lag5"),
        )).alias("ribbon_joint_widening"),
        score(aligned & (pl.col("width_lag5") < pl.col("width_lag10")),
              pl.col("ribbon_width") - pl.col("width_lag5")).alias("ribbon_compress_expand"),
        score(trend & (high_prev > 0), pl.col("close") / high_prev - 1).alias("trend_close_breakout20"),
        score(aligned, location - 0.8).alias("ribbon_range_high"),
        score(trend & (pl.col("low") < pl.col("ma20")) & (pl.col("close") > pl.col("ma20")),
              (pl.col("close") - pl.col("ma20")) / safe_atr).alias("trend_intraday_reclaim20"),
        score(trend & drawdown.is_between(0.02, 0.08), location - 0.7)
        .alias("trend_peak_pullback_strong_close"),
        score(aligned, (1 - ratio_atr) * positive(b)).alias("ribbon_atr_contraction"),
        score(aligned & (pl.col("close") > pl.col("open")),
              positive(ratio_atr - 1) * positive(pl.col("close") - pl.col("open")) / safe_atr)
        .alias("ribbon_atr_expansion_green"),
        score(trend & (pl.col("open") < pl.col("ma5")) & (pl.col("close") > pl.col("ma5")),
              positive(pl.col("close") - pl.col("open")) / safe_atr)
        .alias("trend_intraday_reclaim5"),
    )
    return raw_scores.with_columns(
        [pl.when(pl.col(name).is_finite() & (pl.col(name) > 0))
         .then(pl.col(name)).otherwise(0.0).alias(name) for name in ROUND_FACTORS[1]]
    ).select("day", "vt_symbol", *ROUND_FACTORS[1])


def make_frame(data: Path, round_number: int) -> tuple[pl.DataFrame, dict]:
    old, metadata = make_old_eligible_frame(data)
    features = stock_features(data)
    if round_number == 1:
        scored = score_round_one(features)
    else:
        raise ValueError("this round has not been defined")
    signal_dates = old["day"].unique().to_list()
    scored = scored.filter(pl.col("day").is_in(signal_dates))
    base = old.select("day", "exit_day", "vt_symbol", "intent_return",
                      "worst_case_return", "entry_fill", "unclosed_at_horizon")
    if scored.unique(["day", "vt_symbol"]).height != scored.height:
        raise ValueError("duplicate scored stock dates")
    result = base.join(scored, on=["day", "vt_symbol"], how="left", validate="1:1")
    if result.height != base.height or any(result[name].null_count() for name in ROUND_FACTORS[round_number]):
        raise ValueError("score join lost eligible stock dates")
    metadata["scored_rows"] = result.height
    return result, metadata


def historical_screen(item: dict) -> bool:
    for era in PERIODS:
        value = item[era]
        if value.get("days", 0) < 20 or value.get("signals", 0) < 200:
            return False
        if value.get("signal_mean") is None or value["signal_mean"] <= COST:
            return False
    return True


def run(round_number: int, data: Path, out: Path) -> None:
    plan_path = out / f"round_{round_number:02d}_plan.json"
    result_path = out / f"round_{round_number:02d}.json"
    if result_path.exists():
        raise FileExistsError("preserve old round results")
    if not plan_path.exists():
        raise FileNotFoundError("write the round plan before running")
    specification = json.loads(plan_path.read_text())
    if specification != plan(round_number, data):
        raise RuntimeError("round code or source data changed after planning")
    frame, metadata = make_frame(data, round_number)
    results = []
    for name in ROUND_FACTORS[round_number]:
        item = {"name": name}
        for era, (start, end) in PERIODS.items():
            in_era = frame.filter(pl.col("exit_day") <= end)
            item[era] = measure(in_era, name, (start, end))
        item["historical_screen"] = historical_screen(item)
        results.append(item)
    output = {
        "round": round_number, "plan_sha256": file_hash(plan_path),
        "candidate_count": len(results), "historical_screen_count": sum(x["historical_screen"] for x in results),
        "independent_time_test_available": False,
        "metadata": metadata, "results": results,
    }
    safe_write(result_path, output)
    print(json.dumps({"round": round_number, "candidate_count": len(results),
                      "screen_count": output["historical_screen_count"], "metadata": metadata},
                     ensure_ascii=False))
    for item in results:
        means = [round(item[era].get("signal_mean", 0) * 100, 3) for era in PERIODS]
        edges = [round(item[era].get("edge", 0) * 100, 3) for era in PERIODS]
        print(item["name"], "own_return_pct", means, "edge_pp", edges,
              "screen", item["historical_screen"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("plan", "run"), required=True)
    parser.add_argument("--round", type=int, required=True)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    if args.round not in ROUND_FACTORS:
        raise ValueError("round is not yet predeclared")
    if args.stage == "plan":
        path = args.out / f"round_{args.round:02d}_plan.json"
        safe_write(path, plan(args.round, args.data))
        print(f"planned round {args.round}: {len(ROUND_FACTORS[args.round])} candidates")
    else:
        run(args.round, args.data, args.out)


if __name__ == "__main__":
    main()
