"""Offline unit tests for the historical FX download/aggregation pipeline."""
import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path

from download_forex import HEADERS, candles, milliseconds, months, produce


class ForexPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def make_input(self, rows):
        path = self.root / "monthly.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(HEADERS)
            writer.writerows(rows)
        return path

    def test_month_windows(self):
        self.assertEqual(list(months(date(2021, 11, 12), date(2022, 2, 3))), [
            (date(2021, 11, 12), date(2021, 12, 1)),
            (date(2021, 12, 1), date(2022, 1, 1)),
            (date(2022, 1, 1), date(2022, 2, 1)),
            (date(2022, 2, 1), date(2022, 2, 3)),
        ])

    def test_aggregation_keeps_gaps(self):
        start, end = date(2024, 1, 2), date(2024, 1, 3)
        base = milliseconds(start)
        source = self.make_input([
            (base, 1.10, 1.12, 1.09, 1.11, 5),
            (base + 60_000, 1.11, 1.15, 1.10, 1.14, 3),
            (base + 3_600_000, 1.14, 1.16, 1.13, 1.15, 2),
        ])
        output = produce("EURUSD", "bid", [(source, (start, end))], start, end, self.root)
        self.assertEqual(output["1m"]["rows"], 3)
        self.assertEqual(output["1m"]["non_consecutive_intervals"], 1)
        self.assertEqual(output["1h"]["rows"], 2)
        self.assertEqual(output["4h"]["rows"], 1)
        self.assertEqual(output["1h"]["partial_buckets"], 2)
        with (self.root / output["1h"]["file"]).open(newline="") as f:
            bars = list(csv.DictReader(f))
        self.assertEqual(int(bars[1]["timestamp"]), base + 3_600_000)
        self.assertAlmostEqual(float(bars[0]["high"]), 1.15)
        self.assertAlmostEqual(float(bars[0]["low"]), 1.09)
        self.assertAlmostEqual(float(bars[0]["close"]), 1.14)
        self.assertAlmostEqual(float(bars[0]["volume"]), 8)

    def test_reject_duplicate_bad_ohlc_and_off_grid(self):
        start, end = date(2024, 1, 2), date(2024, 1, 3)
        base = milliseconds(start)
        valid = (base, 1.1, 1.2, 1.0, 1.15, 1)
        for rows in ([valid, valid],
                     [(base, 1.1, 1.09, 1.0, 1.15, 1)],
                     [(base + 123, 1.1, 1.2, 1.0, 1.15, 1)]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                list(candles(self.make_input(rows), start, end))


if __name__ == "__main__":
    unittest.main()
