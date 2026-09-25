"""Follow-up MA study without future-dependent sample exclusions.

Discovery uses teacher data through 2023 and the already-viewed 2024-25 BaoStock
period. The 2026 segment is only evaluated after all candidate rounds are saved.
"""
from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
import math
from pathlib import Path

import polars as pl

from audit_stock_cache import read_cache

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "reports/ma_clean"
TRAIN = (date(2008, 1, 2), date(2016, 12, 31))
VALID = (date(2017, 1, 1), date(2020, 12, 31))
OLD_DEV = (date(2021, 1, 1), date(2023, 12, 31))
NEW_DEV = (date(2024, 1, 1), date(2025, 12, 31))
HOLDOUT = (date(2026, 1, 1), date(2026, 9, 23))
STEP = 6
COST = 0.003  # Illustrative round-trip cost; not an observed execution cost.

ROUND_NAMES: dict[int, list[str]] = {
    1: [
        "gate_trend_control", "gate_pullback_depth", "gate_interaction",
        "gate_trend_plus_depth", "gate_depth_0p5_3", "gate_depth_1_5",
        "gate_depth_under_2", "gate_positive_long_slope", "gate_rebound_day",
        "gate_down_day", "gate_below_ma10", "gate_positive_short_slope",
    ],
    2: [
        "breadth_at_least_45", "breadth_at_least_55", "breadth_at_least_65",
        "breadth_below_45", "breadth_below_55", "market_up_day",
        "market_down_day", "relative_strength_day", "relative_weakness_day",
        "breadth_55_strong_long_gap", "breadth_55_rising_ma20", "weak_breadth_rebound",
    ],
    3: [
        "under_ma20_long_up", "under_ma20_depth", "under_ma20_shallow",
        "under_ma20_deep", "ma5_below20_long_up", "ma5_cross_down_long_up",
        "ma5_cross_up_long_up", "price_reclaim_ma20", "price_reclaim_ma5",
        "long_gap_cross_up", "long_gap_cross_down_rebound", "double_bear_rebound",
    ],
    4: [
        "low_relative_vol", "high_relative_vol", "vol_below_2p5pct",
        "vol_between_2p5_5pct", "volume_ratio_above_1p2", "volume_ratio_below_0p8",
        "vol_scaled_trend_depth", "vol_scaled_depth", "active_volume_weighted_depth",
        "relative_weakness_plus_low_vol", "rising_short_plus_low_vol", "strong_breadth_plus_low_vol",
    ],
}
ROUND_CLUES = {
    1: "Separate long-trend strength from short pullback depth; test depth windows and recovery state",
    2: "After round 1 weakened in 2021-23, condition the same pullback on contemporaneous market breadth",
    3: "Since breadth still gave unstable periods, test transitions across short and long MAs instead of a static pullback",
    4: "After MA transitions weakened, return to the original pullback and condition on known volatility and volume",
}


def add_features(raw: pl.DataFrame) -> pl.DataFrame:
    if "day" not in raw.columns:
        raw = raw.with_columns(pl.col("datetime").dt.date().alias("day"))
    if "tradestatus" not in raw.columns:
        raw = raw.with_columns(pl.lit(1).alias("tradestatus"), pl.lit(0).alias("isST"))
    x = raw.sort(["vt_symbol", "day"])
    x = x.with_columns(
        [pl.col("close").rolling_mean(n).over("vt_symbol").alias(f"ma{n}") for n in (5, 10, 20, 60)]
        + [pl.col("close").shift(1).over("vt_symbol").alias("previous_close")]
    )
    x = x.with_columns(
        pl.col("ma20").shift(5).over("vt_symbol").alias("ma20_lag5"),
        pl.col("ma5").shift(5).over("vt_symbol").alias("ma5_lag5"),
        pl.col("ma20").shift(1).over("vt_symbol").alias("ma20_lag1"),
        pl.col("ma5").shift(1).over("vt_symbol").alias("ma5_lag1"),
        (pl.col("ma20") / pl.col("ma60") - 1).alias("long_gap"),
        (pl.col("ma5") / pl.col("ma20") - 1).alias("short_gap"),
        (pl.col("ma5") / pl.col("close") - 1).alias("depth5"),
        (pl.col("close") / pl.col("previous_close") - 1).alias("day_return"),
        pl.col("volume").rolling_mean(20).over("vt_symbol").alias("volume_mean20"),
    )
    x = x.with_columns(
        (pl.col("ma20") / pl.col("ma20_lag5") - 1).alias("long_slope"),
        (pl.col("ma5") / pl.col("ma5_lag5") - 1).alias("short_slope"),
        pl.col("short_gap").shift(1).over("vt_symbol").alias("short_gap_lag1"),
        pl.col("long_gap").shift(5).over("vt_symbol").alias("long_gap_lag5"),
        pl.col("day_return").rolling_std(20).over("vt_symbol").alias("return_vol20"),
        (pl.col("volume") / pl.col("volume_mean20")).alias("volume_ratio20"),
    )
    return x


def add_factor_batch(x: pl.DataFrame, number: int) -> pl.DataFrame:
    gap = pl.col("long_gap")
    depth = pl.col("depth5")
    gate = (gap > 0) & (pl.col("close") > pl.col("ma20")) & (depth > 0)
    score = lambda condition, value: pl.when(condition).then(value).otherwise(0.0)
    if number == 1:
        expressions = [
            score(gate, gap).alias("gate_trend_control"),
            score(gate, depth).alias("gate_pullback_depth"),
            score(gate, gap * depth).alias("gate_interaction"),
            score(gate, gap + depth).alias("gate_trend_plus_depth"),
            score(gate & depth.is_between(0.005, 0.03), gap).alias("gate_depth_0p5_3"),
            score(gate & depth.is_between(0.01, 0.05), gap).alias("gate_depth_1_5"),
            score(gate & (depth < 0.02), gap).alias("gate_depth_under_2"),
            score(gate & (pl.col("long_slope") > 0), gap).alias("gate_positive_long_slope"),
            score(gate & (pl.col("day_return") > 0), gap).alias("gate_rebound_day"),
            score(gate & (pl.col("day_return") < 0), gap).alias("gate_down_day"),
            score(gate & (pl.col("close") < pl.col("ma10")), gap).alias("gate_below_ma10"),
            score(gate & (pl.col("short_slope") > 0), gap).alias("gate_positive_short_slope"),
        ]
    elif number == 2:
        breadth = pl.col("market_breadth")
        market_ret = pl.col("market_day_return")
        base = gap + depth
        expressions = [
            score(gate & (breadth >= 0.45), base).alias("breadth_at_least_45"),
            score(gate & (breadth >= 0.55), base).alias("breadth_at_least_55"),
            score(gate & (breadth >= 0.65), base).alias("breadth_at_least_65"),
            score(gate & (breadth < 0.45), base).alias("breadth_below_45"),
            score(gate & (breadth < 0.55), base).alias("breadth_below_55"),
            score(gate & (market_ret > 0), base).alias("market_up_day"),
            score(gate & (market_ret < 0), base).alias("market_down_day"),
            score(gate & (pl.col("day_return") > market_ret), base).alias("relative_strength_day"),
            score(gate & (pl.col("day_return") < market_ret), base).alias("relative_weakness_day"),
            score(gate & (breadth >= 0.55) & (gap > 0.02), base).alias("breadth_55_strong_long_gap"),
            score(gate & (breadth >= 0.55) & (pl.col("long_slope") > 0), base).alias("breadth_55_rising_ma20"),
            score(gate & (breadth < 0.45) & (pl.col("day_return") > 0), base).alias("weak_breadth_rebound"),
        ]
    elif number == 3:
        short_gap = pl.col("short_gap")
        below20 = (gap > 0) & (pl.col("close") < pl.col("ma20"))
        depth20 = pl.col("ma20") / pl.col("close") - 1
        expressions = [
            score(below20, gap + depth20).alias("under_ma20_long_up"),
            score(below20, depth20).alias("under_ma20_depth"),
            score(below20 & (depth20 < 0.02), gap + depth20).alias("under_ma20_shallow"),
            score(below20 & depth20.is_between(0.02, 0.06), gap + depth20).alias("under_ma20_deep"),
            score((gap > 0) & (short_gap < 0), gap - short_gap).alias("ma5_below20_long_up"),
            score((gap > 0) & (short_gap < 0) & (pl.col("short_gap_lag1") >= 0), gap - short_gap).alias("ma5_cross_down_long_up"),
            score((gap > 0) & (short_gap > 0) & (pl.col("short_gap_lag1") <= 0), gap + short_gap).alias("ma5_cross_up_long_up"),
            score((gap > 0) & (pl.col("close") > pl.col("ma20")) & (pl.col("previous_close") <= pl.col("ma20_lag1")), gap).alias("price_reclaim_ma20"),
            score((gap > 0) & (pl.col("close") > pl.col("ma5")) & (pl.col("previous_close") <= pl.col("ma5_lag1")), gap).alias("price_reclaim_ma5"),
            score((gap > 0) & (pl.col("long_gap_lag5") <= 0), gap).alias("long_gap_cross_up"),
            score((gap < 0) & (pl.col("long_gap_lag5") >= 0) & (pl.col("close") > pl.col("ma5")), -gap).alias("long_gap_cross_down_rebound"),
            score((gap < 0) & (short_gap < 0) & (pl.col("close") > pl.col("ma5")), -gap - short_gap).alias("double_bear_rebound"),
        ]
    elif number == 4:
        vol = pl.col("return_vol20")
        vol_median = pl.col("vol_median_day")
        vr = pl.col("volume_ratio20")
        base = gap + depth
        low_vol = vol < vol_median
        expressions = [
            score(gate & low_vol, base).alias("low_relative_vol"),
            score(gate & (vol > vol_median), base).alias("high_relative_vol"),
            score(gate & (vol < 0.025), base).alias("vol_below_2p5pct"),
            score(gate & vol.is_between(0.025, 0.05), base).alias("vol_between_2p5_5pct"),
            score(gate & (vr > 1.2), base).alias("volume_ratio_above_1p2"),
            score(gate & (vr < 0.8), base).alias("volume_ratio_below_0p8"),
            score(gate & (vol > 0), base / vol).alias("vol_scaled_trend_depth"),
            score(gate & (vol > 0), depth / vol).alias("vol_scaled_depth"),
            score(gate & (vr > 0), gap + depth * vr).alias("active_volume_weighted_depth"),
            score(gate & low_vol & (pl.col("day_return") < pl.col("market_day_return")), base).alias("relative_weakness_plus_low_vol"),
            score(gate & low_vol & (pl.col("short_slope") > 0), base).alias("rising_short_plus_low_vol"),
            score(gate & low_vol & (pl.col("market_breadth") >= 0.5), base).alias("strong_breadth_plus_low_vol"),
        ]
    else:
        raise ValueError(f"round {number} is not defined")
    assert len(expressions) == len(ROUND_NAMES[number]) == 12
    return x.with_columns(expressions)


def make_frame(
    raw: pl.DataFrame, number: int, source: str, start: date, end: date, membership=None
) -> tuple[pl.DataFrame, dict]:
    """Keep all t-day eligible signals; represent future non-fills explicitly.

    An absent entry bar is a zero-return no-fill. An entry with no exit at the
    fixed horizon is marked to the latest observed close and counted as open;
    a separate -100% stress statistic retains the worst-case bound. Neither
    condition removes a signal from rows.
    """
    x = add_features(raw)
    calendar_days = sorted(x["day"].unique().to_list())
    anchor = next(i for i, day in enumerate(calendar_days) if day >= start)
    if source == "teacher":
        ranges = [(symbol, a.date(), b.date()) for symbol, periods in membership.items() for a, b in periods]
        active = x.join(
            pl.DataFrame(ranges, schema=["vt_symbol", "member_start", "member_end"], orient="row"),
            on="vt_symbol",
        ).filter(pl.col("day").is_between(pl.col("member_start"), pl.col("member_end")))
        if active.unique(["vt_symbol", "day"]).height != active.height:
            raise ValueError("overlapping historical membership")
    else:
        active = x  # The BaoStock downloader freezes the 2023-12-29 membership.
    active = active.with_columns(
        (pl.col("close") > pl.col("ma20")).cast(pl.Float64).mean().over("day").alias("market_breadth"),
        pl.col("day_return").mean().over("day").alias("market_day_return"),
        pl.col("return_vol20").median().over("day").alias("vol_median_day"),
    )
    active = add_factor_batch(active, number)
    calendar = pl.DataFrame(
        {"day": calendar_days[:-6], "entry_day": calendar_days[1:-5], "exit_day": calendar_days[6:]}
    ).with_columns(pl.Series("ordinal", range(len(calendar_days) - 6)))
    calendar = calendar.filter(
        (pl.col("ordinal") >= anchor)
        & ((pl.col("ordinal") - anchor) % STEP == 0)
        & pl.col("day").is_between(start, end)
        & (pl.col("exit_day") <= end)
    )
    active = active.join(calendar.select("day", "entry_day", "exit_day"), on="day")
    potential = active.height
    # Only signal-date information is allowed in the sampling predicate.
    active = active.filter(
        (pl.col("close") > 0)
        & (pl.col("volume") > 0)
        & (pl.col("tradestatus") == 1)
        & (pl.col("isST") == 0)
        & pl.col("long_gap").is_finite()
        & pl.col("depth5").is_finite()
    )
    bars = x.select("vt_symbol", "day", "open", "volume", "tradestatus")
    active = active.join(
        bars.rename({"day": "entry_day", "open": "entry_open", "volume": "entry_volume", "tradestatus": "entry_status"}),
        on=["vt_symbol", "entry_day"], how="left",
    ).join(
        bars.rename({"day": "exit_day", "open": "exit_open", "volume": "exit_volume", "tradestatus": "exit_status"}),
        on=["vt_symbol", "exit_day"], how="left",
    )
    marks = x.select("vt_symbol", "day", "close").rename({"day": "mark_day", "close": "mark_close"})
    active = active.sort("exit_day").join_asof(
        marks.sort("mark_day"), left_on="exit_day", right_on="mark_day",
        by="vt_symbol", strategy="backward",
    )
    active = active.with_columns(
        ((pl.col("entry_open") > 0) & (pl.col("entry_volume") > 0) & (pl.col("entry_status") == 1))
        .fill_null(False).alias("entry_fill"),
        ((pl.col("exit_open") > 0) & (pl.col("exit_volume") > 0) & (pl.col("exit_status") == 1))
        .fill_null(False).alias("exit_fill"),
    )
    active = active.with_columns(
        pl.when(~pl.col("entry_fill")).then(0.0)
        .when(~pl.col("exit_fill")).then(pl.col("mark_close") / pl.col("entry_open") - 1)
        .otherwise(pl.col("exit_open") / pl.col("entry_open") - 1)
        .alias("intent_return"),
        pl.when(~pl.col("entry_fill")).then(0.0)
        .when(~pl.col("exit_fill")).then(-1.0)
        .otherwise(pl.col("exit_open") / pl.col("entry_open") - 1)
        .alias("worst_case_return"),
        (pl.col("entry_fill") & ~pl.col("exit_fill")).alias("unclosed_at_horizon"),
    )
    frame = active.select(
        "day", "exit_day", "vt_symbol", "intent_return", "worst_case_return", "entry_fill", "unclosed_at_horizon",
        *ROUND_NAMES[number],
    )
    return frame, {
        "source": source, "potential_signal_rows": potential, "eligible_t_day_rows": frame.height,
        "sample_dates": frame["day"].n_unique(), "factors": len(ROUND_NAMES[number]),
        "future_volume_or_extreme_move_exclusion": False,
        "entry_no_fill_count_all_eligible": frame.filter(~pl.col("entry_fill")).height,
        "unclosed_count_all_eligible": frame.filter(pl.col("unclosed_at_horizon")).height,
    }


def measure(frame: pl.DataFrame, name: str, period: tuple[date, date]) -> dict:
    a, b = period
    x = frame.filter(pl.col("day").is_between(a, b) & pl.col(name).is_finite())
    if x.is_empty():
        return {"days": 0, "signals": 0, "error": "no rows"}
    x = x.with_columns(
        pl.col(name).rank("average").over("day").alias("score_rank"),
        pl.col("intent_return").rank("average").over("day").alias("target_rank"),
        ((pl.col(name) > 0) & (pl.col(name).rank("ordinal", descending=True).over("day") <= 20))
        .alias("selected"),
    )
    daily = x.group_by("day").agg(
        pl.len().alias("stocks"),
        pl.col("selected").sum().alias("signals"),
        pl.col("intent_return").mean().alias("baseline_mean"),
        pl.col("intent_return").filter(pl.col("selected")).mean().alias("signal_mean"),
        pl.col("intent_return").filter(pl.col("selected")).median().alias("signal_median"),
        pl.col("worst_case_return").filter(pl.col("selected")).mean().alias("signal_worst_case_mean"),
        (pl.col("intent_return") > 0).filter(pl.col("selected")).mean().alias("signal_up_rate"),
        (pl.col("intent_return") > 0).mean().alias("baseline_up_rate"),
        (~pl.col("entry_fill")).filter(pl.col("selected")).sum().alias("signal_entry_no_fills"),
        pl.col("unclosed_at_horizon").filter(pl.col("selected")).sum().alias("signal_unclosed"),
        pl.corr("score_rank", "target_rank").alias("rank_ic"),
    ).filter((pl.col("stocks") >= 50) & (pl.col("signals") >= 1))
    if daily.is_empty():
        return {"days": 0, "signals": 0, "error": "no signal dates"}
    daily = daily.with_columns((pl.col("signal_mean") - pl.col("baseline_mean")).alias("edge"))
    summary = daily.select(
        pl.len().alias("days"), pl.col("signals").sum().alias("signals"),
        pl.col("stocks").mean().alias("stocks_per_day"),
        pl.col("signal_mean").mean().alias("signal_mean"),
        pl.col("signal_median").median().alias("signal_median_across_days"),
        pl.col("signal_worst_case_mean").mean().alias("signal_worst_case_mean"),
        pl.col("baseline_mean").mean().alias("baseline_mean"),
        pl.col("edge").mean().alias("edge"), pl.col("edge").std().alias("edge_sd"),
        pl.col("edge").median().alias("edge_median_across_days"),
        pl.col("signal_up_rate").mean().alias("signal_up_rate"),
        pl.col("baseline_up_rate").mean().alias("baseline_up_rate"),
        pl.col("rank_ic").mean().alias("rank_ic"),
        pl.col("rank_ic").is_finite().sum().alias("rank_ic_days"),
        pl.col("signal_entry_no_fills").sum().alias("entry_no_fills"),
        pl.col("signal_unclosed").sum().alias("unclosed_at_horizon"),
    ).row(0, named=True)
    summary["after_0p3pct_cost_sensitivity"] = summary["signal_mean"] - COST
    if summary["edge_sd"] is not None and summary["days"] > 1:
        half = 1.96 * summary["edge_sd"] / math.sqrt(summary["days"])
        summary["edge_naive_95pct_interval"] = [summary["edge"] - half, summary["edge"] + half]
    return summary


def qualifies(item: dict) -> bool:
    for key, minimum_days in (("train", 60), ("valid", 60), ("old_dev", 30), ("new_dev", 30)):
        result = item[key]
        if result.get("days", 0) < minimum_days or result.get("signals", 0) < 500:
            return False
        if result["signal_mean"] <= COST or result["edge"] <= 0.0015 or (result["rank_ic"] or 0) <= 0.01:
            return False
        if result["rank_ic_days"] < minimum_days // 2:
            return False
    return True


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("teacher_cache", type=Path)
    parser.add_argument("--fresh-parquet", type=Path, default=ROOT / "data/factor_research/ma_research_2026.parquet")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--stage", choices=("explore", "lock", "finalize"), default="explore")
    parser.add_argument("--round", type=int, default=1)
    args = parser.parse_args()
    outdir = args.output_dir
    if (outdir / "final.json").exists():
        raise RuntimeError("2026 holdout has been opened; no further candidate selection")
    teacher_hashes = {p.name: sha256(p.read_bytes()).hexdigest() for p in args.teacher_cache.glob("*.pkl")}
    fresh_hash = sha256(args.fresh_parquet.read_bytes()).hexdigest()
    if args.stage == "explore":
        if (outdir / "selection.json").exists():
            raise RuntimeError("selection is locked; no further candidate rounds")
        number = args.round
        if number not in ROUND_NAMES:
            raise ValueError("round has no predeclared candidate list")
        path = outdir / f"round_{number:02}.json"
        if path.exists():
            raise RuntimeError("round already saved; preserve the audit trail")
        if number > 1 and not (outdir / f"round_{number-1:02}.json").exists():
            raise RuntimeError("rounds must be consecutive")
        teacher, membership = read_cache(args.teacher_cache)
        teacher = teacher.filter(pl.col("datetime").dt.date() <= OLD_DEV[1])
        fresh = pl.read_parquet(args.fresh_parquet).filter(pl.col("day") <= NEW_DEV[1])
        tframe, tdata = make_frame(teacher, number, "teacher", TRAIN[0], OLD_DEV[1], membership)
        fframe, fdata = make_frame(fresh, number, "fresh", NEW_DEV[0], NEW_DEV[1])
        results = []
        for name in ROUND_NAMES[number]:
            item = {"name": name, "train": measure(tframe, name, TRAIN),
                    "valid": measure(tframe, name, VALID),
                    "old_dev": measure(tframe, name, OLD_DEV),
                    "new_dev": measure(fframe, name, NEW_DEV)}
            item["qualifies"] = qualifies(item)
            results.append(item)
        output = {
            "round": number, "clue": ROUND_CLUES[number], "candidate_count": len(results),
            "target": "t+1 open to t+6 open; no entry fill=0; no horizon exit=latest-close mark, separately -100% worst-case stress",
            "sampling": "every 6 market days; top 20 positive-score stocks per day; only t-known eligibility; at least 50 eligible stocks and 1 selected stock per scored date",
            "screen": "all 4 development periods: >=60/60/30/30 days, >=500 top-20 signals, gross >0.3%, edge >0.15pp, rank IC >0.01 on at least half the minimum days",
            "new_2026_test_viewed": False, "teacher_hashes": teacher_hashes,
            "fresh_parquet_sha256": fresh_hash, "teacher_data": tdata, "fresh_data": fdata,
            "results": results,
        }
        save(path, output)
        print("round", number, "candidates", len(results), "qualifying", sum(i["qualifies"] for i in results), "2026 untouched")
        for item in sorted(results, key=lambda i: i["new_dev"].get("edge", -9), reverse=True):
            print(item["name"], "valid_edge", round(item["valid"].get("edge", 0), 5),
                  "old_dev_edge", round(item["old_dev"].get("edge", 0), 5),
                  "new_dev_edge", round(item["new_dev"].get("edge", 0), 5),
                  "qualifies", item["qualifies"])
    elif args.stage == "lock":
        paths = [outdir / f"round_{i:02}.json" for i in range(1, 5)]
        if not all(p.exists() for p in paths):
            raise RuntimeError("all four rounds must finish before locking")
        if (outdir / "selection.json").exists():
            raise RuntimeError("selection is already locked")
        rounds = [json.loads(p.read_text()) for p in paths]
        if any(r["teacher_hashes"] != teacher_hashes or r["fresh_parquet_sha256"] != fresh_hash for r in rounds):
            raise RuntimeError("research data changed since discovery")
        all_candidates = [(r["round"], x) for r in rounds for x in r["results"]]
        periods = ("train", "valid", "old_dev", "new_dev")
        qualified = [(round_no, x) for round_no, x in all_candidates if x["qualifies"]]
        fallback = False
        if qualified:
            pool = qualified
            selection_rule = "maximise minimum development gross return after 0.3% cost among pre-screen qualifiers"
        else:
            fallback = True
            pool = [(round_no, x) for round_no, x in all_candidates if all(
                x[k].get("days", 0) >= 20 and x[k].get("signals", 0) >= 300
                and x[k]["signal_mean"] > COST and x[k]["edge"] > 0
                for k in periods
            )]
            selection_rule = "diagnostic fallback: all four periods positive after-cost gross and positive edge, >=20 days and 300 selections; maximise weakest after-cost gross"
        if not pool:
            fallback = True
            pool = [(round_no, x) for round_no, x in all_candidates if all(
                x[k].get("days", 0) >= 20 and x[k].get("signals", 0) >= 300 for k in periods
            )]
            selection_rule = "diagnostic fallback: adequate coverage, maximise weakest development edge"
            if not pool:
                raise RuntimeError("no candidate has enough development coverage")
            key = lambda pair: (min(pair[1][k]["edge"] for k in periods),
                                min(pair[1][k]["signal_mean"] - COST for k in periods), pair[1]["name"])
        else:
            key = lambda pair: (min(pair[1][k]["signal_mean"] - COST for k in periods),
                                min(pair[1][k]["edge"] for k in periods), pair[1]["name"])
        chosen_round, chosen = max(pool, key=key)
        selection = {
            "selected": chosen["name"], "round": chosen_round,
            "qualified_all_development_periods": chosen["qualifies"],
            "fallback_diagnostic_only": fallback, "selection_rule": selection_rule,
            "selection_pool_size": len(pool), "development": {k: chosen[k] for k in periods},
            "teacher_hashes": teacher_hashes, "fresh_parquet_sha256": fresh_hash,
            "locked_code_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
            "holdout_viewed": False,
        }
        save(outdir / "selection.json", selection)
        print("locked", chosen["name"], "round", chosen_round,
              "qualified", chosen["qualifies"], "fallback", fallback, "2026 untouched")
    else:
        selection_path = outdir / "selection.json"
        if not selection_path.exists():
            raise RuntimeError("lock a single candidate before opening 2026 holdout")
        selection = json.loads(selection_path.read_text())
        if selection["teacher_hashes"] != teacher_hashes or selection["fresh_parquet_sha256"] != fresh_hash:
            raise RuntimeError("data differs from the locked selection")
        if selection["locked_code_sha256"] != sha256(Path(__file__).read_bytes()).hexdigest():
            raise RuntimeError("research code changed after selection was locked")
        fresh = pl.read_parquet(args.fresh_parquet)
        frame, data = make_frame(fresh, selection["round"], "fresh", HOLDOUT[0], HOLDOUT[1])
        result = measure(frame, selection["selected"], HOLDOUT)
        interval = result.get("edge_naive_95pct_interval")
        ideal = (
            selection["qualified_all_development_periods"]
            and result.get("days", 0) >= 20 and result.get("signals", 0) >= 250
            and result.get("signal_mean", -1) > COST
            and interval is not None and interval[0] > 0
            and (result.get("rank_ic") or 0) > 0.01
        )
        output = {
            "selected": selection["selected"], "round": selection["round"],
            "fallback_diagnostic_only": selection["fallback_diagnostic_only"],
            "ideal_by_predeclared_rule": ideal,
            "ideal_rule": "development qualifier plus 2026 >=20 non-overlapping sample dates, >=250 selected stocks, mean after 0.3% illustrative cost >0, naive daily edge 95% lower bound >0, rank IC >0.01",
            "holdout_period": [str(v) for v in HOLDOUT], "holdout": result,
            "holdout_data": data, "fresh_parquet_sha256": fresh_hash,
            "selection_sha256": sha256(selection_path.read_bytes()).hexdigest(),
            "holdout_viewed_once": True,
        }
        save(outdir / "final.json", output)
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
