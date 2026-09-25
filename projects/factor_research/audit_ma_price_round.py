"""Reproduce exploratory moving-block intervals for MA+price rounds 3/4."""
from __future__ import annotations

from pathlib import Path
import argparse
import json

import numpy as np
import polars as pl

import ma_price_research as base
import ma_price_round3 as round3
import ma_price_round4 as round4
from audit_ma_dense_days import block_interval


def audit(number: int) -> dict:
    module = {3: round3, 4: round4}[number]
    score_fn = {3: round3.score_round_three, 4: round4.score_round_four}[number]
    old, _ = base.make_frame(base.DATA, 1)
    scores = score_fn(base.DATA).filter(pl.col("day").is_in(old["day"].unique().to_list()))
    frame = old.select("day", "exit_day", "vt_symbol", "intent_return").join(
        scores, on=["day", "vt_symbol"], validate="1:1")
    output = {
        "method": "4-signal-day circular moving-block bootstrap; 4000 repetitions; signal-day equal weight; historical exploratory only",
        "cost_assumption": base.COST,
        "round": number,
        "candidate_selection_bias_adjusted": False,
        "results": {},
    }
    for i, name in enumerate(module.NAMES):
        output["results"][name] = {}
        for j, (era, (start, end)) in enumerate(base.PERIODS.items()):
            x = frame.filter(pl.col("day").is_between(start, end) & (pl.col("exit_day") <= end))
            x = x.with_columns(
                ((pl.col(name) > 0) &
                 (pl.col(name).rank("ordinal", descending=True).over("day") <= 20)).alias("selected"))
            daily = x.group_by("day").agg(
                pl.col("intent_return").filter(pl.col("selected")).mean().alias("mean")
            ).sort("day")
            values = np.array([v if v is not None else np.nan for v in daily["mean"].to_list()])
            ci = block_interval(values, 4, 20260924 + 100 * i + j)
            output["results"][name][era] = {
                "days": int(np.isfinite(values).sum()),
                "gross_mean": float(np.nanmean(values)),
                "net_assumption_ci95": [float(ci[0] - base.COST), float(ci[1] - base.COST)],
            }
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", type=int, choices=(3, 4), required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    destination = args.out or (base.OUT / f"round_{args.round:02d}_diagnostic.json")
    result = audit(args.round)
    with destination.open("x") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    print(f"round {args.round}: {len(result['results'])} exploratory candidates")
    for name, periods in result["results"].items():
        lower = [round(v["net_assumption_ci95"][0] * 100, 3) for v in periods.values()]
        print(name, "net_lower_pct", lower, "positive_all", all(x > 0 for x in lower))


if __name__ == "__main__":
    main()
