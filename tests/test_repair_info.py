from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from tools import repair_info


class RepairInfoTests(unittest.TestCase):
    def test_repair_snapshot_replaces_same_event_but_keeps_distinct_repair(self):
      with tempfile.TemporaryDirectory() as directory:
        first = Path(directory) / "first.xlsx"
        second = Path(directory) / "second.xlsx"
        first.touch()
        second.touch()
        first_frame = pd.DataFrame({
        "PCB": ["4190000123", "4190000123"],
        "Barcode": ["863000112233", "863000112233"],
        "model": ["Model A", "Model A"],
        "TestTime": ["2026-07-01 08:00:00", "2026-07-02 08:00:00"],
        "BadMachEntryTime": ["2026-07-01 08:00:00", "2026-07-02 08:00:00"],
        "RepairDate": ["2026-07-01 10:00:00", "2026-07-02 11:00:00"],
        "TestOperation": ["Download", "Download"],
        "Fault Phenomenon": ["Fault A", "Fault B"],
        "Repairer": ["A", "B"],
        "RepairTimes": [1, 2],
        })
        second_frame = first_frame.iloc[[0]].copy()
        second_frame["RepairDate"] = "2026-07-01 12:00:00"
        second_frame["Repairer"] = "C"
        with patch.object(repair_info.pd, "read_excel", side_effect=lambda path, **_: first_frame if Path(path) == first else second_frame):
            events, audit = repair_info.combine_repair_files({"SMT": [], "Assembly": [first, second]})

        self.assertEqual(audit["duplicates"], 1)
        self.assertEqual(len(events), 2)
        updated = events.loc[events["Fault Phenomenon"].eq("Fault A")].iloc[0]
        self.assertEqual(updated["Repairer"], "C")
        self.assertEqual(updated["Elapsed (h)"], 4)
        self.assertEqual(repair_info.repair_summary(events)["pcbs"], 1)
        daily = repair_info.daily_summary(events, date(2026, 7, 1), date(2026, 7, 3))
        self.assertEqual(daily["Assembly"].tolist(), [1, 1, 0])


    def test_repair_summary_excludes_invalid_durations_without_losing_daily_volume(self):
      events = pd.DataFrame({
        "Area": ["SMT", "SMT", "Assembly"],
        "PCB SN": ["A", "A", "A"],
        "Repair day": pd.to_datetime(["2026-09-01"] * 3),
        "Elapsed (h)": [2.0, pd.NA, 4.0],
      })

      result = repair_info.repair_summary(events)

      self.assertEqual(result["pcbs"], 2)
      self.assertEqual(result["events"], 3)
      self.assertEqual(result["avg_h"], 3)
      self.assertEqual(result["median_h"], 3)
      self.assertEqual(round(result["coverage_pct"], 1), 66.7)
      daily = repair_info.daily_summary(events, date(2026, 9, 1), date(2026, 9, 1))
      self.assertEqual(daily.iloc[0]["SMT"], 1)
      self.assertEqual(daily.iloc[0]["Assembly"], 1)


if __name__ == "__main__":
    unittest.main()
