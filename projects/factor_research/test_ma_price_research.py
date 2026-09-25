"""Check that future bars cannot change already formed MA + OHLC scores."""
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import polars as pl
from polars.testing import assert_frame_equal

from ma_price_research import ROUND_FACTORS, score_round_one, stock_features
from ma_price_round3 import NAMES as ROUND3_NAMES, score_round_three
from ma_price_round4 import NAMES as ROUND4_NAMES, score_round_four


class CausalScoreTest(unittest.TestCase):
    def test_future_price_change_leaves_prior_scores_unchanged(self) -> None:
        start = date(2024, 1, 1)
        rows = []
        for i in range(165):
            price = 10 + i * 0.02 + (i % 7) * 0.005
            rows.append({
                "date": str(start + timedelta(days=i)), "code": "sh.600000",
                "open": price - 0.03, "high": price + 0.08,
                "low": price - 0.10, "close": price,
                "volume": 10000.0, "tradestatus": 1,
            })
        with TemporaryDirectory() as directory:
            path = Path(directory) / "bars_qfq.parquet"
            pl.DataFrame(rows).write_parquet(path)
            before = score_round_one(stock_features(Path(directory)))
            changed = [dict(row) for row in rows]
            changed[160].update(open=100.0, high=111.0, low=90.0, close=105.0)
            pl.DataFrame(changed).write_parquet(path)
            after = score_round_one(stock_features(Path(directory)))
        cutoff = start + timedelta(days=159)
        left = before.filter(pl.col("day") <= cutoff).select("day", *ROUND_FACTORS[1])
        right = after.filter(pl.col("day") <= cutoff).select("day", *ROUND_FACTORS[1])
        assert_frame_equal(left, right)

    def test_future_bar_leaves_gap_and_volume_combinations_unchanged(self) -> None:
        start = date(2024, 1, 1)
        rows = []
        for i in range(175):
            price = 10 + i * 0.01 + i * i * 0.0005
            rows.append({
                "date": str(start + timedelta(days=i)), "code": "sh.600000",
                "open": price + 0.03, "high": price + 0.10,
                "low": price - 0.10, "close": price,
                "volume": 10000.0 + (i % 5) * 1000, "tradestatus": 1,
            })
        with TemporaryDirectory() as directory:
            path = Path(directory) / "bars_qfq.parquet"
            pl.DataFrame(rows).write_parquet(path)
            before3 = score_round_three(Path(directory))
            before4 = score_round_four(Path(directory))
            changed = [dict(row) for row in rows]
            changed[170].update(open=200.0, high=230.0, low=190.0,
                                close=205.0, volume=999999.0)
            pl.DataFrame(changed).write_parquet(path)
            after3 = score_round_three(Path(directory))
            after4 = score_round_four(Path(directory))
        cutoff = start + timedelta(days=169)
        for before, after, names in ((before3, after3, ROUND3_NAMES),
                                     (before4, after4, ROUND4_NAMES)):
            left = before.filter(pl.col("day") <= cutoff).select("day", *names)
            right = after.filter(pl.col("day") <= cutoff).select("day", *names)
            assert_frame_equal(left, right)
        self.assertGreater(before3["gap_up_only"].max(), 0)


if __name__ == "__main__":
    unittest.main()
