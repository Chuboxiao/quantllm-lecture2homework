"""Fetch a fixed, pre-2024 CSI500 cohort for cross-universe transfer testing.

Anonymous BaoStock data only. The cohort date is fixed before any return is
computed. Raw files remain in a Git-ignored local data directory.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from hashlib import sha256
from pathlib import Path
import argparse
import json

import baostock as bs
import polars as pl

from download_csi300_history import _fetch_bars, _login, _atomic_json


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/factor_research/csi500_2023_fixed"
ASOF = "2023-12-29"
BEGIN = "2023-05-01"
END = "2026-09-23"


def file_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_members(out: Path) -> None:
    target = out / "members.json"
    if target.exists():
        raise FileExistsError("fixed cohort already saved")
    out.mkdir(parents=True, exist_ok=True)
    _login()
    try:
        query = bs.query_zz500_stocks(ASOF)
        if query.error_code != "0":
            raise RuntimeError(f"CSI500 membership: {query.error_code} {query.error_msg}")
        rows = query.data
        if len(rows) != 500 or len({row[1] for row in rows}) != 500:
            raise ValueError(f"expected 500 distinct CSI500 codes, got {len(rows)} rows")
        if any(len(row) != 3 or row[0] > ASOF for row in rows):
            raise ValueError("unexpected historical membership date or schema")
        result = {
            "provider": "BaoStock", "provider_version": getattr(bs, "__version__", "unknown"),
            "requested_asof": ASOF, "returned_update_dates": sorted({row[0] for row in rows}),
            "retrieved_at": datetime.now().astimezone().isoformat(),
            "codes": sorted(row[1] for row in rows),
        }
        _atomic_json(target, result)
        print("saved fixed CSI500 members", len(result["codes"]), flush=True)
    finally:
        bs.logout()


def get_bars(out: Path, workers: int) -> None:
    members_path = out / "members.json"
    if not members_path.exists():
        raise FileNotFoundError("get members before bars")
    members = json.loads(members_path.read_text())
    if members["requested_asof"] != ASOF or len(members["codes"]) != 500:
        raise ValueError("unexpected member file")
    bars_path = out / "bars_qfq.parquet"
    if bars_path.exists():
        raise FileExistsError("preserve existing raw bars")
    parts = out / ".parts"
    parts.mkdir(parents=True, exist_ok=True)
    pending = [(code, BEGIN, END, str(parts / f"{code}.parquet"))
               for code in members["codes"] if not (parts / f"{code}.parquet").exists()]
    if pending:
        completed = 0
        errors = []
        with ProcessPoolExecutor(max_workers=workers, initializer=_login) as pool:
            futures = {pool.submit(_fetch_bars, *task): task[0] for task in pending}
            for future in as_completed(futures):
                code = futures[future]
                try:
                    future.result()
                    completed += 1
                except Exception as exc:
                    errors.append(f"{code}: {type(exc).__name__}: {exc}")
                if completed % 25 == 0 and completed:
                    print(f"downloaded {completed}/{len(pending)} pending stocks", flush=True)
        if errors:
            raise RuntimeError(f"{len(errors)} download failures; first: {errors[:5]}")
    frames = [pl.read_parquet(parts / f"{code}.parquet") for code in members["codes"]]
    bars = pl.concat(frames).sort(["code", "date"])
    if bars.select(pl.struct("code", "date").n_unique()).item() != bars.height:
        raise ValueError("duplicate stock dates")
    if bars.filter((pl.col("high") < pl.col("low")) | (pl.col("close") > pl.col("high"))).height:
        raise ValueError("invalid price bar")
    bars.write_parquet(bars_path, compression="zstd")
    summary = {
        "provider": "BaoStock", "asof_membership": ASOF,
        "begin": BEGIN, "end": END, "adjustflag": "2 (front-adjusted)",
        "members": len(members["codes"]), "bar_rows": bars.height,
        "first_bar": bars["date"].min(), "last_bar": bars["date"].max(),
        "membership_sha256": file_hash(members_path), "bars_sha256": file_hash(bars_path),
        "retrieved_at": datetime.now().astimezone().isoformat(),
    }
    _atomic_json(out / "manifest.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("members", "bars"), required=True)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if args.phase == "members":
        get_members(args.out)
    elif 1 <= args.workers <= 4:
        get_bars(args.out, args.workers)
    else:
        raise ValueError("workers must be 1-4")


if __name__ == "__main__":
    main()
