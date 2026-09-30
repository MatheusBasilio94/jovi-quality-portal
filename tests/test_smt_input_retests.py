import unittest
from io import BytesIO

import pandas as pd

from tools.smt_quality_dashboard import read_summary_input_bytes


class SMTInputRetestTests(unittest.TestCase):
    @staticmethod
    def workbook(org_rows):
        model = pd.DataFrame([
            {"model": "PD2607LF_BR", "Input": 24, "BadMachine": 0,
             "BeginDate": "2026-09-29", "EndDate": "2026-09-29"},
            {"model": "PD2541YF_BR", "Input": 1, "BadMachine": 0,
             "BeginDate": "2026-09-29", "EndDate": "2026-09-29"},
        ])
        org = pd.DataFrame([
            {"model": name, "DisplayMode": line, "Input": count, "BadMachine": bad,
             "BeginDate": "2026-09-29", "EndDate": "2026-09-29"}
            for name, line, count, bad in org_rows
        ])
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            model.to_excel(writer, sheet_name="ModelData", index=False)
            org.to_excel(writer, sheet_name="OrgDisplay", index=False)
        return buffer.getvalue()

    def test_extra_line_input_does_not_inflate_kpi_denominator(self):
        data = self.workbook([
            ("PD2607LF_BR", "B01ST101", 24, 0),
            ("PD2607LF_BR", "B01SF101", 3, 0),
            ("PD2541YF_BR", "B01ST101", 1, 0),
        ])
        model, org, audit = read_summary_input_bytes(data, "retest.xlsx")
        self.assertEqual(model["Input"].sum(), 25)
        self.assertEqual(org["Input"].sum(), 28)
        self.assertEqual(audit["OrgExcessInput"], 3)
        self.assertFalse(audit["OrgReconciles"])

    def test_rejects_short_org_input_or_different_bad_machine(self):
        for org_rows in (
            [("PD2607LF_BR", "B01ST101", 23, 0), ("PD2541YF_BR", "B01ST101", 1, 0)],
            [("PD2607LF_BR", "B01ST101", 24, 1), ("PD2541YF_BR", "B01ST101", 1, 0)],
            [("PD2607LF_BR", "B01ST101", 23, 0), ("PD2541YF_BR", "B01ST101", 2, 0)],
        ):
            with self.subTest(org_rows=org_rows):
                with self.assertRaisesRegex(RuntimeError, "do not reconcile by model and day"):
                    read_summary_input_bytes(self.workbook(org_rows), "bad.xlsx")


if __name__ == "__main__":
    unittest.main()
