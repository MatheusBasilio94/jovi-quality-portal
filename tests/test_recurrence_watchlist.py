import unittest
from datetime import date

import pandas as pd

from tools.recurrence_watchlist import build_recurrence_watchlist


class RecurrenceWatchlistTests(unittest.TestCase):
    def test_recurring_issue_uses_unique_pcbs_per_week_and_marks_persistent(self):
        records = pd.DataFrame(
            [
                {"PCB": "A", "KPIDate": "2026-09-01", "RepaireRemark": "Loose connector", "Operation": "Station 1", "Model": "M1"},
                {"PCB": "A", "KPIDate": "2026-09-02", "RepaireRemark": "Loose connector", "Operation": "Station 1", "Model": "M1"},
                {"PCB": "A", "KPIDate": "2026-09-08", "RepaireRemark": "Loose connector", "Operation": "Station 1", "Model": "M1"},
                {"PCB": "B", "KPIDate": "2026-09-15", "RepaireRemark": "Loose connector", "Operation": "Station 2", "Model": "M2"},
                {"PCB": "C", "KPIDate": "2026-09-16", "RepaireRemark": "Single occurrence", "Operation": "Station 3", "Model": "M3"},
            ]
        )

        result = build_recurrence_watchlist(records, date(2026, 9, 1), date(2026, 9, 16))
        watchlist = result["watchlist"]

        self.assertEqual(list(watchlist["TopIssue"]), ["Loose connector"])
        row = watchlist.iloc[0]
        self.assertEqual(row["Priority"], "Critical")
        self.assertEqual(row["AffectedPCBs"], 2)
        self.assertEqual(row["ActiveWeeks"], 3)
        self.assertEqual(row["RecidivistPCBs"], 1)
        self.assertEqual(result["summary"]["persistent_issues"], 1)


if __name__ == "__main__":
    unittest.main()
