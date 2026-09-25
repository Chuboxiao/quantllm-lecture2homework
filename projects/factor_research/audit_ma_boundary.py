"""Audit a period-boundary issue without changing the locked factor study.

The original metrics selected by signal date but allowed a train/validation
label to end just beyond that period. This recalculates development metrics
after enforcing exit_day <= period end. It never evaluates 2026 returns.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

import polars as pl

from audit_stock_cache import read_cache
from ma_clean_research import TRAIN, VALID, OLD_DEV, make_frame, measure, qualifies

ROOT = Path(__file__).resolve().parents[2]
PERIODS = {"train": TRAIN, "valid": VALID, "old_dev": OLD_DEV}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("teacher_cache", type=Path)
    args = parser.parse_args()
    report_dir = ROOT / "reports/ma_clean"
    selection = json.loads((report_dir / "selection.json").read_text())
    code_hash = sha256((Path(__file__).parent / "ma_clean_research.py").read_bytes()).hexdigest()
    if code_hash != selection["locked_code_sha256"]:
        raise RuntimeError("locked research code changed; cannot compare metrics")
    teacher, membership = read_cache(args.teacher_cache)
    teacher = teacher.filter(pl.col("datetime").dt.date() <= OLD_DEV[1])
    corrected = []
    changed = []
    crossing = {}
    for number in range(1, 5):
        published = json.loads((report_dir / f"round_{number:02}.json").read_text())
        frame, _ = make_frame(teacher, number, "teacher", TRAIN[0], OLD_DEV[1], membership)
        crossing[number] = {}
        for label, (start, end) in PERIODS.items():
            affected = frame.filter(pl.col("day").is_between(start, end) & (pl.col("exit_day") > end))
            crossing[number][label] = {"dates": affected["day"].n_unique(), "rows": affected.height}
        for item in published["results"]:
            fixed = {"name": item["name"], "new_dev": item["new_dev"], "round": number}
            for label, period in PERIODS.items():
                clipped = frame.filter(pl.col("exit_day") <= period[1])
                fixed[label] = measure(clipped, item["name"], period)
                original = item[label]
                check_fields = ("days", "signals", "signal_mean", "edge", "rank_ic")
                materially_changed = any(
                    (fixed[label].get(field) is None) != (original.get(field) is None)
                    or (fixed[label].get(field) is not None and original.get(field) is not None
                        and abs(fixed[label][field] - original[field]) > 1e-9)
                    for field in check_fields
                )
                if materially_changed:
                    changed.append({
                        "round": number, "name": item["name"], "period": label,
                        "old_days": original["days"], "new_days": fixed[label]["days"],
                        "old_signal_mean": original.get("signal_mean"),
                        "new_signal_mean": fixed[label].get("signal_mean"),
                        "old_edge": original.get("edge"), "new_edge": fixed[label].get("edge"),
                    })
            fixed["qualifies"] = qualifies(fixed)
            corrected.append(fixed)
    all_periods = ("train", "valid", "old_dev", "new_dev")
    pool = [x for x in corrected if x["qualifies"]]
    if pool:
        rule = "qualified"
    else:
        rule = "same four-positive-period diagnostic fallback"
        pool = [x for x in corrected if all(
            x[key].get("days", 0) >= 20 and x[key].get("signals", 0) >= 300
            and x[key]["signal_mean"] > 0.003 and x[key]["edge"] > 0
            for key in all_periods
        )]
    if not pool:
        raise RuntimeError("fallback pool changed; investigate before comparison")
    chosen = max(pool, key=lambda x: (
        min(x[key]["signal_mean"] - 0.003 for key in all_periods),
        min(x[key]["edge"] for key in all_periods), x["name"],
    ))
    output = {
        "scope": "development period-boundary correction only; 2026 holdout not reevaluated",
        "locked_code_sha256": code_hash,
        "crossing_rows_by_round": crossing,
        "changed_metrics_count": len(changed), "changed_metrics": changed,
        "corrected_qualifiers": [x["name"] for x in corrected if x["qualifies"]],
        "corrected_fallback_pool_size": len(pool), "corrected_selection_rule": rule,
        "original_selected": selection["selected"], "corrected_selected": chosen["name"],
        "selection_unchanged": selection["selected"] == chosen["name"],
        "corrected_selected_development": {key: chosen[key] for key in all_periods},
    }
    path = report_dir / "boundary_audit.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str) + "\n")
    print("changed metrics", len(changed), "corrected qualifiers", len(output["corrected_qualifiers"]),
          "selection unchanged", output["selection_unchanged"])


if __name__ == "__main__":
    main()
