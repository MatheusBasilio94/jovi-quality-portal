import unittest
from io import BytesIO

import pandas as pd

from tools.smt_quality_dashboard import read_summary_input_bytes


class SMTInputReconciliationTests(unittest.TestCase):
    def test_station_retests_are_audited_without_inflating_model_input(self):
        output = BytesIO()
        shared = {"model": "PD2607LF_BR", "BadMachine": 0,
                  "BeginDate": "2026-09-29", "EndDate": "2026-09-29"}
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            pd.DataFrame([{**shared, "Input": 24}]).to_excel(
                writer, sheet_name="ModelData", index=False)
            pd.DataFrame([{**shared, "Input": 24, "DisplayMode": "AOI"},
                          {**shared, "Input": 3, "DisplayMode": "Retest"}]).to_excel(
                writer, sheet_name="OrgDisplay", index=False)
        model, _, audit = read_summary_input_bytes(output.getvalue(), "20260929.xlsx")
        self.assertEqual(int(model["Input"].sum()), 24)
        self.assertEqual(audit["OrgInputDifference"], 3)
        self.assertFalse(audit["OrgReconciles"])


if __name__ == "__main__":
    unittest.main()
