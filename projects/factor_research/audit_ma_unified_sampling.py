"""Post-hoc sensitivity of the old MA pullback clue to 2026 sampling and stock pool.

This is an audit of already-viewed dates, not a factor-selection or holdout test.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import argparse
import json

import baostock as bs
import polars as pl

from download_csi300_history import _fetch_membership, _hash, _login
from ma_clean_research import measure
from ma_unified_research import DATA, OUT, make_frame


def calendar_days(frame: pl.DataFrame) -> list[date]:
    return [date.fromisoformat(day) for day, active in frame.iter_rows() if active == 1]


def score_case(tmp: Path, calendar: pl.DataFrame, membership: pl.DataFrame) -> dict:
    tmp.mkdir(parents=True)
    (tmp / "bars_qfq.parquet").symlink_to((DATA / "bars_qfq.parquet").resolve())
    calendar.write_parquet(tmp / "trade_calendar.parquet")
    membership.write_parquet(tmp / "membership_signal_days.parquet")
    frame, meta = make_frame(tmp)
    end = date(2026, 9, 23)
    result = measure(frame.filter(pl.col("exit_day") <= end),
                     "old_market_down_pullback", (date(2026, 1, 1), end))
    return {"first_signal_day": str(membership["asof_date"].min()),
            "sample_dates": membership["asof_date"].n_unique(),
            "eligible_rows_all_calendar": meta["eligible_t_day_rows"],
            "result": result}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all-offsets", action="store_true")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    if args.all_offsets:
        output_path = args.out / "offsets_audit.json"
        if output_path.exists():
            raise FileExistsError("offset audit already exists")
        full_calendar = pl.read_parquet(DATA / "trade_calendar.parquet")
        recent_calendar = full_calendar.filter(pl.col("date") >= "2026-01-01")
        days = calendar_days(recent_calendar)
        weekly = pl.read_parquet(DATA / "membership_weekly.parquet")
        fixed = weekly.filter(pl.col("asof_date") == "2023-12-25").select("code", "code_name")
        if fixed.height != 300:
            raise ValueError("fixed pool must contain 300 symbols")
        cases = {}
        with TemporaryDirectory(prefix="pku-ma-offsets-") as scratch:
            for offset in range(6):
                shifted_calendar = recent_calendar.filter(pl.col("date") >= str(days[offset]))
                sample_dates = [str(day) for day in calendar_days(shifted_calendar)[:-6:6]]
                members = pl.DataFrame({"asof_date": sample_dates}).join(fixed, how="cross")
                cases[str(offset)] = score_case(Path(scratch) / f"offset_{offset}",
                                                shifted_calendar, members)
        output = {"posthoc_diagnostic_only": True,
                  "universe": "2023-12-25 fixed CSI300 300-stock pool",
                  "factor": "old_market_down_pullback",
                  "period": "2026-01-01 to 2026-09-23, already viewed",
                  "offset": "number of market trading days skipped from 2026-01-05 before every-sixth-day sampling",
                  "cases": cases}
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
        for offset, item in cases.items():
            result = item["result"]
            print(offset, item["first_signal_day"], "signal_days", result.get("days"),
                  "mean", result.get("signal_mean"), "edge", result.get("edge"))
        return
    out = args.out / "sampling_audit.json"
    if out.exists():
        raise FileExistsError("sampling audit exists; do not overwrite")
    full = pl.read_parquet(DATA / "trade_calendar.parquet")
    recent = full.filter(pl.col("date") >= "2026-01-01")
    reset_dates = [str(day) for day in calendar_days(recent)[:-6:6]]
    parts = DATA / ".parts/2026_reset_members"
    parts.mkdir(parents=True, exist_ok=True)
    pending = [day for day in reset_dates if not (parts / f"{day}.json").exists()]
    if pending:
        _login()
        try:
            for day in pending:
                _fetch_membership(day, str(parts / f"{day}.json"))
        finally:
            bs.logout()
    reset_rows = []
    for day in reset_dates:
        content = json.loads((parts / f"{day}.json").read_text())
        for update_date, code, name in content["rows"]:
            reset_rows.append({"asof_date": day, "update_date": update_date,
                               "code": code, "code_name": name})
    reset_members = pl.DataFrame(reset_rows)
    if reset_members.height != len(reset_dates) * 300:
        raise ValueError("incomplete reset-date membership")
    cached_reset = parts / "membership_reset.parquet"
    reset_members.write_parquet(cached_reset)
    global_dynamic = pl.read_parquet(DATA / "membership_signal_days.parquet")
    weekly = pl.read_parquet(DATA / "membership_weekly.parquet")
    base = weekly.filter(pl.col("asof_date") == "2023-12-25").select("code", "code_name")
    if base.height != 300:
        raise ValueError("2023-12-25 fixed pool is not 300")

    def frozen(dates: list[str]) -> pl.DataFrame:
        return pl.DataFrame({"asof_date": dates}).join(base, how="cross")

    with TemporaryDirectory(prefix="pku-ma-sampling-") as scratch:
        root = Path(scratch)
        cases = {
            "global_every6_dynamic_pool": score_case(root / "a", full, global_dynamic),
            "global_every6_frozen_2023_pool": score_case(
                root / "b", full, frozen(sorted(global_dynamic["asof_date"].unique().to_list()))),
            "reset_2026_every6_dynamic_pool": score_case(root / "c", recent, reset_members),
            "reset_2026_every6_frozen_2023_pool": score_case(
                root / "d", recent, frozen(reset_dates)),
        }
    output = {"posthoc_diagnostic_only": True,
              "description": "Same old market-down pullback score, four combinations of sample anchor and member pool; 2026 already viewed",
              "reset_membership_sha256": _hash(cached_reset), "cases": cases}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    for key, value in cases.items():
        r = value["result"]
        print(key, "days", r.get("days"), "signal_mean", r.get("signal_mean"),
              "edge", r.get("edge"))


if __name__ == "__main__":
    main()
