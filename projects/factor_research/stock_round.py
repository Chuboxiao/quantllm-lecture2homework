"""Reproducible moving-average clue research on the supplied stock cache.

Explore: calculate train/validation only, without viewing test metrics.
Finalize: choose automatically from saved validation metrics, then evaluate test once.
Data are research prices, not a tradable-price execution backtest.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
from hashlib import sha256
import json
from pathlib import Path

import polars as pl

from audit_stock_cache import read_cache

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/stock_factors"
START = date(2008, 1, 2)
END = date(2023, 12, 29)
PERIODS = {"train": (date(2008, 1, 2), date(2016, 12, 31)),
           "valid": (date(2017, 1, 1), date(2020, 12, 31)),
           "test": (date(2021, 1, 1), END)}
HOLD_DAYS = 5
STEP = 6
ROUNDTRIP_COST_SENSITIVITY = 0.003  # Illustrative assumption, not measured execution cost.

# All factor values are computed at the close of signal date t. Positive values
# encode the bullish version of the clue, independently of other stocks.
ROUND_1 = {
    "ma5_ma20": "MA5 / MA20 - 1",
    "ma10_ma40": "MA10 / MA40 - 1",
    "ma5_ma60": "MA5 / MA60 - 1",
    "close_ma20": "close / MA20 - 1",
    "return_5": "close / close[t-5] - 1",
    "return_10": "close / close[t-10] - 1",
    "return_20": "close / close[t-20] - 1",
    "ma5_slope_3": "MA5 / MA5[t-3] - 1",
    "ma20_slope_5": "MA20 / MA20[t-5] - 1",
    "gap_change_5": "MA5/MA20 - (MA5/MA20)[t-5]",
    "slope_difference": "(MA5/MA5[t-3]-1) - (MA20/MA20[t-5]-1)",
    "volume_weighted_return_10": "sum(return_1 * volume,10) / sum(volume,10)",
}
ROUND_2 = {
    "revert_ma5_ma20": "1 - MA5/MA20",
    "revert_ma10_ma40": "1 - MA10/MA40",
    "revert_ma5_ma60": "1 - MA5/MA60",
    "revert_close_ma20": "1 - close/MA20",
    "revert_return_5": "1 - close/close[t-5]",
    "revert_return_10": "1 - close/close[t-10]",
    "revert_return_20": "1 - close/close[t-20]",
    "revert_ma5_slope_3": "1 - MA5/MA5[t-3]",
    "revert_ma20_slope_5": "1 - MA20/MA20[t-5]",
    "revert_gap_change_5": "(MA5/MA20)[t-5] - MA5/MA20",
    "revert_volume_weighted_10": "-sum(return_1 * volume,10)/sum(volume,10)",
    "pullback_in_uptrend": "1-close/MA20 + 0.25*(MA20/MA60-1)",
}
ROUND_3 = {
    "volume_surprise": "volume/mean(volume,20)-1",
    "volume_dryup": "1-volume/mean(volume,20)",
    "volume_trend_5": "return_5 * volume/mean(volume,20)",
    "volume_reversal_5": "-return_5 * volume/mean(volume,20)",
    "trend_5_plus_volume": "return_5 + 0.02*(volume/mean(volume,20)-1)",
    "reversal_5_plus_volume": "-return_5 + 0.02*(volume/mean(volume,20)-1)",
    "ma_trend_plus_volume": "MA5/MA20-1 + 0.02*(volume/mean(volume,20)-1)",
    "ma_revert_plus_volume": "1-MA5/MA20 + 0.02*(volume/mean(volume,20)-1)",
    "strong_trend_5": "return_5/std(return_1,20)-1",
    "strong_reversal_5": "-return_5/std(return_1,20)-1",
    "strong_ma_trend": "(MA5/MA20-1)/std(return_1,20)-1",
    "strong_ma_revert": "(1-MA5/MA20)/std(return_1,20)-1",
}
ROUND_4 = {
    "breakout_high_20": "close / previous 20-bar high - 1",
    "breakout_high_10": "close / previous 10-bar high - 1",
    "breakdown_low_20": "previous 20-bar low / close - 1",
    "breakdown_low_10": "previous 10-bar low / close - 1",
    "near_high_20": "close / previous 20-bar high - 0.98",
    "near_low_20": "1.02 - close / previous 20-bar low",
    "upper_range_20": "(close-low20)/(high20-low20) - 0.5",
    "lower_range_20": "0.5 - (close-low20)/(high20-low20)",
    "volatility_contraction": "1 - std(return_1,10)/std(return_1,40)",
    "volatility_expansion": "std(return_1,10)/std(return_1,40) - 1",
    "quiet_ma_trend": "MA5/MA20-1 + 0.02*(1-std10/std40)",
    "volatile_ma_revert": "1-close/MA20 + 0.02*(std10/std40-1)",
}
ROUNDS = {1: ROUND_1, 2: ROUND_2, 3: ROUND_3, 4: ROUND_4}

def stock_frame(cache: Path) -> tuple[pl.DataFrame, dict]:
    df, intervals = read_cache(cache)
    required = {"datetime", "vt_symbol", "open", "high", "low", "close", "volume"}
    if not required <= set(df.columns):
        raise ValueError(f"Cache missing columns: {required-set(df.columns)}")
    df = df.sort(["vt_symbol", "datetime"]).with_columns(pl.col("datetime").dt.date().alias("day"))
    df = df.with_columns([
        pl.col("close").rolling_mean(n).over("vt_symbol").alias(f"ma{n}") for n in (5,10,20,40,60)
    ] + [pl.col("close").shift(n).over("vt_symbol").alias(f"lag{n}") for n in (1,5,10,20)])
    df = df.with_columns([
        pl.col("ma5").shift(3).over("vt_symbol").alias("ma5_lag3"),
        pl.col("ma5").shift(5).over("vt_symbol").alias("ma5_lag5"),
        pl.col("ma20").shift(5).over("vt_symbol").alias("ma20_lag5"),
        (pl.col("close")/pl.col("lag1")-1).alias("return1"),
    ])
    df = df.with_columns((pl.col("return1").abs()>0.25).fill_null(False).alias("large_jump"))
    df = df.with_columns([
        pl.col("large_jump").cast(pl.Int8).rolling_max(60).over("vt_symbol").fill_null(0).alias("recent_jump"),
        pl.max_horizontal([pl.col("large_jump").cast(pl.Int8).shift(-n).over("vt_symbol").fill_null(0) for n in range(1,7)]).alias("future_jump"),
        (pl.col("return1")*pl.col("volume")).rolling_sum(10).over("vt_symbol").alias("vr_num10"),
        pl.col("volume").rolling_sum(10).over("vt_symbol").alias("vr_den10"),
    ])
    df = df.with_columns([
        (pl.col("ma5")/pl.col("ma20")-1).alias("ma5_ma20"),
        (pl.col("ma10")/pl.col("ma40")-1).alias("ma10_ma40"),
        (pl.col("ma5")/pl.col("ma60")-1).alias("ma5_ma60"),
        (pl.col("close")/pl.col("ma20")-1).alias("close_ma20"),
        (pl.col("close")/pl.col("lag5")-1).alias("return_5"),
        (pl.col("close")/pl.col("lag10")-1).alias("return_10"),
        (pl.col("close")/pl.col("lag20")-1).alias("return_20"),
        (pl.col("ma5")/pl.col("ma5_lag3")-1).alias("ma5_slope_3"),
        (pl.col("ma20")/pl.col("ma20_lag5")-1).alias("ma20_slope_5"),
        (pl.col("ma5")/pl.col("ma20")-pl.col("ma5_lag5")/pl.col("ma20_lag5")).alias("gap_change_5"),
        ((pl.col("ma5")/pl.col("ma5_lag3")-1)-(pl.col("ma20")/pl.col("ma20_lag5")-1)).alias("slope_difference"),
        (pl.col("vr_num10")/pl.col("vr_den10")).alias("volume_weighted_return_10"),
    ])
    df = df.with_columns([
        (-pl.col("ma5_ma20")).alias("revert_ma5_ma20"),
        (-pl.col("ma10_ma40")).alias("revert_ma10_ma40"),
        (-pl.col("ma5_ma60")).alias("revert_ma5_ma60"),
        (-pl.col("close_ma20")).alias("revert_close_ma20"),
        (-pl.col("return_5")).alias("revert_return_5"),
        (-pl.col("return_10")).alias("revert_return_10"),
        (-pl.col("return_20")).alias("revert_return_20"),
        (-pl.col("ma5_slope_3")).alias("revert_ma5_slope_3"),
        (-pl.col("ma20_slope_5")).alias("revert_ma20_slope_5"),
        (-pl.col("gap_change_5")).alias("revert_gap_change_5"),
        (-pl.col("volume_weighted_return_10")).alias("revert_volume_weighted_10"),
        (-pl.col("close_ma20")+0.25*(pl.col("ma20")/pl.col("ma60")-1)).alias("pullback_in_uptrend"),
    ])
    df = df.with_columns([
        (pl.col("volume")/pl.col("volume").rolling_mean(20).over("vt_symbol")).alias("volume_ratio"),
        pl.col("return1").rolling_std(20).over("vt_symbol").alias("return_vol20"),
        pl.col("return1").rolling_std(10).over("vt_symbol").alias("return_vol10"),
        pl.col("return1").rolling_std(40).over("vt_symbol").alias("return_vol40"),
        pl.col("high").rolling_max(20).shift(1).over("vt_symbol").alias("prev_high20"),
        pl.col("high").rolling_max(10).shift(1).over("vt_symbol").alias("prev_high10"),
        pl.col("low").rolling_min(20).shift(1).over("vt_symbol").alias("prev_low20"),
        pl.col("low").rolling_min(10).shift(1).over("vt_symbol").alias("prev_low10"),
        pl.col("high").rolling_max(20).over("vt_symbol").alias("high20"),
        pl.col("low").rolling_min(20).over("vt_symbol").alias("low20"),
    ])
    df = df.with_columns([
        (pl.col("volume_ratio")-1).alias("volume_surprise"),
        (1-pl.col("volume_ratio")).alias("volume_dryup"),
        (pl.col("return_5")*pl.col("volume_ratio")).alias("volume_trend_5"),
        (-pl.col("return_5")*pl.col("volume_ratio")).alias("volume_reversal_5"),
        (pl.col("return_5")+0.02*(pl.col("volume_ratio")-1)).alias("trend_5_plus_volume"),
        (-pl.col("return_5")+0.02*(pl.col("volume_ratio")-1)).alias("reversal_5_plus_volume"),
        (pl.col("ma5_ma20")+0.02*(pl.col("volume_ratio")-1)).alias("ma_trend_plus_volume"),
        (-pl.col("ma5_ma20")+0.02*(pl.col("volume_ratio")-1)).alias("ma_revert_plus_volume"),
        (pl.col("return_5")/pl.col("return_vol20")-1).alias("strong_trend_5"),
        (-pl.col("return_5")/pl.col("return_vol20")-1).alias("strong_reversal_5"),
        (pl.col("ma5_ma20")/pl.col("return_vol20")-1).alias("strong_ma_trend"),
        (-pl.col("ma5_ma20")/pl.col("return_vol20")-1).alias("strong_ma_revert"),
    ])
    location=(pl.col("close")-pl.col("low20"))/(pl.col("high20")-pl.col("low20"))
    volatility_ratio=pl.col("return_vol10")/pl.col("return_vol40")
    df = df.with_columns([
        (pl.col("close")/pl.col("prev_high20")-1).alias("breakout_high_20"),
        (pl.col("close")/pl.col("prev_high10")-1).alias("breakout_high_10"),
        (pl.col("prev_low20")/pl.col("close")-1).alias("breakdown_low_20"),
        (pl.col("prev_low10")/pl.col("close")-1).alias("breakdown_low_10"),
        (pl.col("close")/pl.col("prev_high20")-0.98).alias("near_high_20"),
        (1.02-pl.col("close")/pl.col("prev_low20")).alias("near_low_20"),
        (location-0.5).alias("upper_range_20"),
        (0.5-location).alias("lower_range_20"),
        (1-volatility_ratio).alias("volatility_contraction"),
        (volatility_ratio-1).alias("volatility_expansion"),
        (pl.col("ma5_ma20")+0.02*(1-volatility_ratio)).alias("quiet_ma_trend"),
        (-pl.col("close_ma20")+0.02*(volatility_ratio-1)).alias("volatile_ma_revert"),
    ])
    ranges = [(s,a.date(),b.date()) for s,ivs in intervals.items() for a,b in ivs]
    membership = pl.DataFrame(ranges, schema=["vt_symbol", "member_start", "member_end"], orient="row")
    active = df.join(membership, on="vt_symbol").filter(pl.col("day").is_between(pl.col("member_start"),pl.col("member_end")))
    if active.unique(["vt_symbol", "day"]).height != active.height:
        raise ValueError("Overlapping membership intervals duplicate stock-days")
    days = sorted(df["day"].unique().to_list())
    anchor = days.index(START)
    calendar = pl.DataFrame({"day": days[:-6], "entry_day": days[1:-5], "exit_day": days[6:]})
    calendar = calendar.with_columns(pl.Series("ordinal", range(len(calendar))))
    calendar = calendar.filter((pl.col("ordinal")>=anchor)&((pl.col("ordinal")-anchor)%STEP==0)&pl.col("day").is_between(START,END))
    active = active.join(calendar.select("day","entry_day","exit_day"), on="day")
    bars = df.select("vt_symbol","day","open","volume")
    active = active.join(bars.rename({"day":"entry_day","open":"entry_open","volume":"entry_volume"}),on=["vt_symbol","entry_day"],how="left")
    active = active.join(bars.rename({"day":"exit_day","open":"exit_open","volume":"exit_volume"}),on=["vt_symbol","exit_day"],how="left")
    raw_count = active.height
    active = active.with_columns((pl.col("exit_open")/pl.col("entry_open")-1).alias("forward_return"))
    active = active.filter((pl.col("volume")>0)&(pl.col("entry_volume")>0)&(pl.col("exit_volume")>0)&
                           (pl.col("recent_jump")==0)&(pl.col("future_jump")==0)&
                           pl.col("forward_return").is_finite())
    result = active.select("day","exit_day","vt_symbol","forward_return",*(name for batch in ROUNDS.values() for name in batch))
    metadata = {"raw_member_signal_rows":raw_count,"eligible_rows":result.height,
                "sample_dates":result["day"].n_unique(),"calendar_step":STEP,
                "eligibility":"member at signal t; nonzero volume at t, t+1 and t+6; excludes features within 60 stock bars after >25% close jump and labels crossing such a jump; finite return",
                "normalized_prices":True,"historical_membership_applied":True,
                "unresolved":"Corporate-action adjustment and actual fillability not verified; future-volume filter is ex-post censoring."}
    return result, metadata

def segment_metrics(frame: pl.DataFrame, factor: str, segment: str) -> dict:
    start,end = PERIODS[segment]
    x = frame.filter(pl.col("day").is_between(start,end)&(pl.col("exit_day")<=end)&pl.col(factor).is_finite())
    if x.is_empty():
        return {"days":0,"signals":0,"error":"no eligible rows"}
    x = x.with_columns([
        pl.col(factor).rank("average").over("day").alias("factor_rank"),
        pl.col("forward_return").rank("average").over("day").alias("return_rank")])
    daily = x.group_by("day").agg([
        pl.len().alias("stocks"),
        (pl.col(factor)>0).sum().alias("signals"),
        pl.col("forward_return").mean().alias("baseline_mean"),
        pl.col("forward_return").filter(pl.col(factor)>0).mean().alias("signal_mean"),
        (pl.col("forward_return")>0).filter(pl.col(factor)>0).mean().alias("signal_up_rate"),
        (pl.col("forward_return")>0).mean().alias("baseline_up_rate"),
        pl.corr("factor_rank","return_rank").alias("rank_ic")])
    daily = daily.filter((pl.col("stocks")>=50)&(pl.col("signals")>=20)&pl.col("rank_ic").is_finite())
    if daily.is_empty():
        return {"days":0,"signals":0,"error":"insufficient daily cross-sections"}
    daily = daily.with_columns((pl.col("signal_mean")-pl.col("baseline_mean")).alias("edge"))
    out = daily.select(
        pl.len().alias("days"),pl.col("signals").sum().alias("signals"),
        pl.col("stocks").mean().alias("stocks_per_day"),
        pl.col("signal_mean").mean().alias("signal_mean"),
        pl.col("baseline_mean").mean().alias("baseline_mean"),
        pl.col("signal_up_rate").mean().alias("signal_up_rate"),
        pl.col("baseline_up_rate").mean().alias("baseline_up_rate"),
        pl.col("edge").mean().alias("edge"),
        pl.col("edge").std().alias("edge_daily_sd"),
        (pl.col("edge")>0).mean().alias("edge_positive_day_fraction"),
        pl.col("rank_ic").mean().alias("rank_ic"),
        pl.col("rank_ic").std().alias("rank_ic_daily_sd")
    ).row(0,named=True)
    out["signal_return_after_0p3pct_cost_sensitivity"] = out["signal_mean"] - ROUNDTRIP_COST_SENSITIVITY
    return out

def qualifies(item: dict) -> bool:
    for segment in ("train","valid"):
        m = item[segment]
        if m.get("days",0)<50 or m.get("signals",0)<500:
            return False
        if not (m["signal_mean"]>0 and m["edge"]>0 and m["rank_ic"]>0):
            return False
    return True

def save_json(path: Path, obj: dict):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str)+"\n")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("cache_directory",type=Path)
    parser.add_argument("--stage",choices=["explore","finalize"],default="explore")
    parser.add_argument("--round",type=int,choices=sorted(ROUNDS),default=1)
    parser.add_argument("--output-dir",type=Path,default=OUT,
                        help="Use a fresh directory for an independent reproduction run")
    args=parser.parse_args()
    out_dir=args.output_dir
    if args.stage=="explore" and (out_dir/"final.json").exists():
        raise RuntimeError("Final test already viewed; this experiment is closed")
    frame, metadata = stock_frame(args.cache_directory)
    source = {f.name:sha256(f.read_bytes()).hexdigest() for f in args.cache_directory.glob("*.pkl")}
    if args.stage=="explore":
        if args.round > 1 and not (out_dir/f"round_{args.round-1:02}.json").exists():
            raise RuntimeError("Explore rounds in order")
        output_path=out_dir/f"round_{args.round:02}.json"
        if output_path.exists():
            raise RuntimeError("Round results already recorded; preserve the audit trail")
        results=[]
        for name,expression in ROUNDS[args.round].items():
            result={"name":name,"expression":expression,
                    "train":segment_metrics(frame,name,"train"),
                    "valid":segment_metrics(frame,name,"valid")}
            result["qualifies_train_valid"]=qualifies(result)
            results.append(result)
        clue = {1:"moving-average and price-volume trend",
                2:"short-term reversal and pullback within a longer trend",
                3:"volume surprise and volatility-adjusted trend/reversal",
                4:"breakouts, price location, and volatility regimes"}[args.round]
        output={"round":args.round,"clue":clue+" predicts each stock's own future return",
                "target":"t+1 open to t+6 open return (5 trading-day intervals)",
                "segments":{k:[str(a),str(b)] for k,(a,b) in PERIODS.items()},
                "primary":"signal>0 conditional mean forward return and excess over same-day universe baseline, equally averaged across sampled days",
                "secondary":"daily Spearman rank IC of continuous factor vs forward return",
                "selection":"train and valid signal_mean>0, edge>0, rank_ic>0; each >=50 days and 500 signals; choose largest valid edge",
                "test_viewed":False,"cache_hashes":source,"data":metadata,"results":results}
        save_json(output_path,output)
        choices=[x for x in results if x["qualifies_train_valid"]]
        print("Round",args.round,"candidates",len(results),"qualifying",len(choices),"train/valid only; test not viewed")
        for x in sorted(results,key=lambda r:r["valid"].get("edge",-999),reverse=True):
            print(x["name"],"train edge",round(x["train"].get("edge",0),5),"valid edge",round(x["valid"].get("edge",0),5),"valid rankIC",round(x["valid"].get("rank_ic",0),4),"qualifies",x["qualifies_train_valid"])
        print(output_path)
    else:
        paths=sorted(out_dir.glob("round_??.json"))
        if not paths:raise RuntimeError("Run exploration first")
        if (out_dir/"final.json").exists():raise RuntimeError("Test already viewed; do not re-run selection")
        rounds=[json.loads(path.read_text()) for path in paths]
        if any(prior["cache_hashes"] != source for prior in rounds):raise RuntimeError("Cache changed since exploration")
        choices=[(prior["round"],x) for prior in rounds for x in prior["results"] if x["qualifies_train_valid"]]
        if not choices:
            print("No candidate passed train and validation. Test remains unviewed; redesign next round or report no retained factor.")
            return
        selected_round,winner=max(choices,key=lambda pair:pair[1]["valid"]["edge"])
        result={"selected":winner["name"],"selected_round":selected_round,"selection_based_on":"train/valid round files only; maximum validation edge among qualifying candidates",
                "train":winner["train"],"valid":winner["valid"],
                "test":segment_metrics(frame,winner["name"],"test"),"test_viewed_once":True,
                "cache_hashes":source,"data":metadata}
        save_json(out_dir/"final.json",result)
        print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
