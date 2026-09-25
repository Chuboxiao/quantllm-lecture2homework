"""Resumable, anonymous BaoStock download for historical CSI 300 research.

Weekly membership snapshots are observations, not a claim of exact daily membership.
Raw data stays in the Git-ignored data directory. No SimNow or trading API is used.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
import argparse
import json
import os
import time

import baostock as bs
import polars as pl


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "data/factor_research/baostock_csi300_history"
FIELDS = "date,code,open,high,low,close,preclose,volume,amount,turn,tradestatus,pctChg,isST"
BAR_SCHEMA = {
    "date": pl.String, "code": pl.String,
    "open": pl.Float64, "high": pl.Float64, "low": pl.Float64,
    "close": pl.Float64, "preclose": pl.Float64,
    "volume": pl.Float64, "amount": pl.Float64, "turn": pl.Float64,
    "tradestatus": pl.Int8, "pctChg": pl.Float64, "isST": pl.Int8,
}


def _login() -> None:
    last_error = "unknown"
    for attempt in range(5):
        try:
            result = bs.login()
            if result.error_code == "0":
                return
            last_error = f"{result.error_code} {result.error_msg}"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"BaoStock login after retries: {last_error}")


def _rows(result) -> list[list[str]]:
    if result.error_code != "0":
        raise RuntimeError(f"BaoStock query: {result.error_code} {result.error_msg}")
    rows = []
    while result.next():
        rows.append(result.get_row_data())
    if result.error_code != "0":
        raise RuntimeError(f"BaoStock stream: {result.error_code} {result.error_msg}")
    return rows


def _atomic_json(path: Path, value: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    os.replace(tmp, path)


def _atomic_parquet(path: Path, frame: pl.DataFrame) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.write_parquet(tmp, compression="zstd")
    os.replace(tmp, path)


def _fetch_membership(day: str, path: str) -> tuple[str, int]:
    destination = Path(path)
    for attempt in range(3):
        try:
            rows = _rows(bs.query_hs300_stocks(day))
            if len(rows) != 300:
                raise ValueError(f"{day}: expected 300 members, got {len(rows)}")
            if any(len(row) != 3 for row in rows):
                raise ValueError(f"{day}: unexpected membership fields")
            _atomic_json(destination, {"asof_date": day, "rows": rows})
            return day, len(rows)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
            try:
                bs.logout()
            except Exception:
                pass
            _login()
    raise AssertionError("unreachable")


def _float(value: str) -> float | None:
    return float(value) if value else None


def _int(value: str) -> int | None:
    return int(value) if value else None


def _fetch_bars(code: str, begin: str, end: str, path: str) -> tuple[str, int]:
    destination = Path(path)
    for attempt in range(3):
        try:
            query = bs.query_history_k_data_plus(
                code, FIELDS, start_date=begin, end_date=end,
                frequency="d", adjustflag="2",
            )
            rows = _rows(query)
            parsed = []
            for row in rows:
                if len(row) != len(BAR_SCHEMA) or row[1] != code:
                    raise ValueError(f"{code}: unexpected bar row")
                parsed.append({
                    "date": row[0], "code": row[1],
                    "open": _float(row[2]), "high": _float(row[3]),
                    "low": _float(row[4]), "close": _float(row[5]),
                    "preclose": _float(row[6]), "volume": _float(row[7]),
                    "amount": _float(row[8]), "turn": _float(row[9]),
                    "tradestatus": _int(row[10]), "pctChg": _float(row[11]),
                    "isST": _int(row[12]),
                })
            if not parsed:
                raise ValueError(f"{code}: no bars in requested range")
            frame = pl.DataFrame(parsed, schema=BAR_SCHEMA)
            if frame.select(pl.struct("code", "date").n_unique()).item() != frame.height:
                raise ValueError(f"{code}: duplicate dates")
            _atomic_parquet(destination, frame)
            return code, len(parsed)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
            try:
                bs.logout()
            except Exception:
                pass
            _login()
    raise AssertionError("unreachable")


def _run_batch(tasks: list[tuple], worker, workers: int, label: str) -> None:
    if not tasks:
        print(f"{label}: already complete", flush=True)
        return
    errors = []
    completed = 0
    with ProcessPoolExecutor(max_workers=workers, initializer=_login) as pool:
        futures = {pool.submit(worker, *task): task[0] for task in tasks}
        for future in as_completed(futures):
            completed += 1
            try:
                future.result()
            except Exception as exc:
                errors.append(f"{futures[future]}: {type(exc).__name__}: {exc}")
            if completed % 25 == 0 or completed == len(tasks):
                print(f"{label}: {completed}/{len(tasks)}, errors={len(errors)}", flush=True)
    if errors:
        raise RuntimeError(f"{label}: {len(errors)} failures; rerun to resume. Examples: {errors[:5]}")


def _hash(path: Path) -> str:
    h = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--begin", default="2008-01-01")
    parser.add_argument("--warmup-begin", default="2007-09-01")
    parser.add_argument("--end", default="2026-09-23")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--phase", choices=("all", "members", "bars", "signal-members"), default="all")
    args = parser.parse_args()
    if not (date.fromisoformat(args.warmup_begin) <= date.fromisoformat(args.begin)
            <= date.fromisoformat(args.end)):
        raise ValueError("invalid date range")
    if not 1 <= args.workers <= 8:
        raise ValueError("workers must be 1 to 8")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    state = out / ".parts"
    members_parts = state / "members"
    bars_parts = state / "bars"
    members_parts.mkdir(parents=True, exist_ok=True)
    bars_parts.mkdir(parents=True, exist_ok=True)
    calendar_path = out / "trade_calendar.parquet"
    if not calendar_path.exists():
        _login()
        try:
            rows = _rows(bs.query_trade_dates(start_date=args.begin, end_date=args.end))
        finally:
            bs.logout()
        if not rows or any(len(row) != 2 for row in rows):
            raise ValueError("empty or malformed trading calendar")
        calendar = pl.DataFrame({
            "date": [row[0] for row in rows],
            "is_trading_day": [int(row[1]) for row in rows],
        })
        _atomic_parquet(calendar_path, calendar)
    calendar = pl.read_parquet(calendar_path)
    trading_days = [date.fromisoformat(day) for day, active in calendar.iter_rows()
                    if active == 1]
    if not trading_days:
        raise ValueError("no trading days")
    if args.phase == "signal-members":
        signal_parts = state / "signal_members"
        signal_parts.mkdir(parents=True, exist_ok=True)
        signal_dates = [trading_days[i].isoformat()
                        for i in range(0, len(trading_days) - 6, 6)]
        pending = [(day, str(signal_parts / f"{day}.json"))
                   for day in signal_dates if not (signal_parts / f"{day}.json").exists()]
        print(f"exact signal-date snapshots: {len(signal_dates)}, pending={len(pending)}", flush=True)
        _run_batch(pending, _fetch_membership, args.workers, "signal-members")
        rows = []
        for day in signal_dates:
            content = json.loads((signal_parts / f"{day}.json").read_text())
            for update_date, code, name in content["rows"]:
                rows.append({"asof_date": day, "update_date": update_date,
                             "code": code, "code_name": name})
        frame = pl.DataFrame(rows)
        if frame.height != len(signal_dates) * 300:
            raise ValueError("incomplete signal-date membership")
        signal_path = out / "membership_signal_days.parquet"
        _atomic_parquet(signal_path, frame)
        manifest_path = out / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            manifest["exact_signal_day_snapshots"] = len(signal_dates)
            manifest["exact_signal_members_retrieved_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            manifest["files"][signal_path.name] = {
                "sha256": _hash(signal_path), "bytes": signal_path.stat().st_size,
            }
            _atomic_json(manifest_path, manifest)
        print(f"exact signal-date snapshots complete: {len(signal_dates)}", flush=True)
        return
    weeks = {}
    for day in trading_days:
        weeks.setdefault(day.isocalendar()[:2], day)
    snapshot_dates = sorted({day.isoformat() for day in weeks.values()}
                            | {trading_days[-1].isoformat()})
    if args.phase in ("all", "members"):
        pending = [(day, str(members_parts / f"{day}.json"))
                   for day in snapshot_dates if not (members_parts / f"{day}.json").exists()]
        print(f"membership snapshots: {len(snapshot_dates)}, pending={len(pending)}", flush=True)
        _run_batch(pending, _fetch_membership, args.workers, "members")
    missing = [day for day in snapshot_dates if not (members_parts / f"{day}.json").exists()]
    if missing:
        raise RuntimeError(f"missing membership snapshots: {len(missing)}")
    member_rows = []
    for day in snapshot_dates:
        content = json.loads((members_parts / f"{day}.json").read_text())
        for update_date, code, name in content["rows"]:
            member_rows.append({"asof_date": day, "update_date": update_date,
                                "code": code, "code_name": name})
    memberships = pl.DataFrame(member_rows)
    if memberships.group_by("asof_date").len().select(pl.col("len").min()).item() != 300:
        raise ValueError("incomplete membership snapshot")
    _atomic_parquet(out / "membership_weekly.parquet", memberships)
    codes = sorted(memberships["code"].unique().to_list())
    print(f"distinct historical members: {len(codes)}", flush=True)
    if args.phase in ("all", "bars"):
        pending = [(code, args.warmup_begin, args.end,
                    str(bars_parts / f"{code}.parquet"))
                   for code in codes if not (bars_parts / f"{code}.parquet").exists()]
        print(f"daily bar symbols: {len(codes)}, pending={len(pending)}", flush=True)
        _run_batch(pending, _fetch_bars, args.workers, "bars")
    missing = [code for code in codes if not (bars_parts / f"{code}.parquet").exists()]
    if missing:
        if args.phase == "members":
            print(f"membership phase complete; {len(missing)} bar symbols not downloaded", flush=True)
            return
        raise RuntimeError(f"missing bar symbols: {len(missing)}")
    bars_path = out / "bars_qfq.parquet"
    temp_bars = bars_path.with_suffix(".parquet.tmp")
    pl.scan_parquet(str(bars_parts / "*.parquet")).sink_parquet(
        temp_bars, compression="zstd",
    )
    os.replace(temp_bars, bars_path)
    bars = pl.scan_parquet(bars_path)
    stats = bars.select(
        pl.len().alias("rows"), pl.col("code").n_unique().alias("symbols"),
        pl.col("date").min().alias("first"), pl.col("date").max().alias("last"),
        (pl.col("volume") == 0).sum().alias("zero_volume_rows"),
        (pl.col("tradestatus") != 1).sum().alias("nontrading_rows"),
        (pl.col("isST") == 1).sum().alias("st_rows"),
    ).collect().to_dicts()[0]
    if stats["symbols"] != len(codes):
        raise ValueError("combined bars lack some members")
    basic_path = out / "stock_basic.parquet"
    if not basic_path.exists():
        _login()
        try:
            query = bs.query_stock_basic()
            basic_rows = _rows(query)
            basic_fields = query.fields
        finally:
            bs.logout()
        if not basic_rows or "code" not in basic_fields:
            raise ValueError("empty or malformed stock basic data")
        basic = pl.DataFrame(basic_rows, schema=basic_fields, orient="row")
        _atomic_parquet(basic_path, basic)
    basic = pl.read_parquet(basic_path)
    basic_codes = set(basic["code"].to_list())
    file_names = ["trade_calendar.parquet", "membership_weekly.parquet",
                  "bars_qfq.parquet", "stock_basic.parquet"]
    signal_path = out / "membership_signal_days.parquet"
    if signal_path.exists():
        file_names.append(signal_path.name)
    manifest = {
        "provider": "BaoStock", "version": getattr(bs, "__version__", "unknown"),
        "retrieved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "requested_member_begin": args.begin, "warmup_begin": args.warmup_begin,
        "requested_end": args.end, "adjustflag": "2: forward adjusted at retrieval time",
        "fields": FIELDS.split(","), "membership_rule": "first trading day of each ISO week, plus final trading day; snapshot only",
        "trading_days": len(trading_days), "membership_snapshots": len(snapshot_dates),
        "historical_member_symbols": len(codes), "daily_bars": stats,
        "stock_basic_rows": basic.height,
        "historical_members_missing_basic": sorted(set(codes) - basic_codes),
        "files": {name: {"sha256": _hash(out / name), "bytes": (out / name).stat().st_size}
                  for name in file_names},
        "limits": ["Weekly membership snapshots may miss intraweek changes.",
                   "Adjusted prices are revised when provider adjustment factors change.",
                   "Not a fillable-trades or independently unseen holdout dataset."],
    }
    _atomic_json(out / "manifest.json", manifest)
    print(json.dumps({"complete": True, **stats, "membership_snapshots": len(snapshot_dates)},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
