"""Check that a signal remains counted when future bars cannot be traded."""
from datetime import date, timedelta
import unittest

import polars as pl

from ma_clean_research import make_frame


class TestNoFutureExclusion(unittest.TestCase):
    def test_missing_future_bars_remain_as_no_fill_or_open_position(self) -> None:
        days = [date(2024, 1, 1) + timedelta(days=i) for i in range(90)]
        rows = []
        for symbol in ("AAA.SSE", "BBB.SSE"):
            for i, day in enumerate(days):
                if symbol == "AAA.SSE" and i in (61, 72):
                    continue  # Missing entry for t=60 and exit for t=66.
                price = 100 + i / 10
                rows.append({"day": day, "vt_symbol": symbol, "open": price,
                             "close": price, "volume": 1000.0,
                             "tradestatus": 1, "isST": 0})
        frame, data = make_frame(pl.DataFrame(rows), 1, "fresh", days[60], days[89])
        no_entry = frame.filter((pl.col("day") == days[60]) & (pl.col("vt_symbol") == "AAA.SSE"))
        no_exit = frame.filter((pl.col("day") == days[66]) & (pl.col("vt_symbol") == "AAA.SSE"))
        self.assertEqual(no_entry.height, 1)
        self.assertFalse(no_entry["entry_fill"][0])
        self.assertEqual(no_entry["intent_return"][0], 0.0)
        self.assertEqual(no_exit.height, 1)
        self.assertTrue(no_exit["unclosed_at_horizon"][0])
        self.assertEqual(no_exit["worst_case_return"][0], -1.0)
        self.assertGreater(data["entry_no_fill_count_all_eligible"], 0)
        self.assertGreater(data["unclosed_count_all_eligible"], 0)


if __name__ == "__main__":
    unittest.main()
