import tempfile
import unittest
from datetime import date
from io import BytesIO
from pathlib import Path

import pandas as pd

from tools import assembly_kpi_v2, smt_quality_dashboard


class AssemblyValidatedRulesTest(unittest.TestCase):
    def write_book(self, path: Path, sheet: str, frame: pd.DataFrame) -> None:
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            frame.to_excel(writer, sheet_name=sheet, index=False)

    def test_period_deduplication_classification_and_final_responsibility(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_paths = []
            for day in (1, 2):
                path = root / f"input-{day}.xlsx"
                self.write_book(
                    path,
                    "ModelData",
                    pd.DataFrame(
                        [{"model": "M1", "Input": 100, "BeginDate": f"2026-09-0{day}", "EndDate": f"2026-09-0{day}"}]
                    ),
                )
                input_paths.append(path)

            events = [
                # Repeated PCB: two daily NGs, one unique PCB in the selected period.
                ("A", "2026-09-01 08:00", "Audio-Testing", "F-A1", "Dayshift assembly group mando"),
                ("A", "2026-09-02 08:00", "Audio-Testing", "F-A2", "Dayshift assembly group mando"),
                # Appearance Mando must never enter Function Mando.
                ("B", "2026-09-01 09:00", "Appearance-QC", "A-B", "Dayshift assembly group mando"),
                # No repair match: retain the FPY responsibility.
                ("C", "2026-09-01 10:00", "Audio-Testing", "F-C", "Dayshift assembly group mando"),
                # Complete repair reclassifies SMT to Assembly Mando.
                ("D", "2026-09-01 11:00", "Audio-Testing", "F-D", "SMT Process"),
                # Complete repair reclassifies Assembly Mando to an allowed SMT duty.
                ("E", "2026-09-01 12:00", "Audio-Testing", "F-E", "Dayshift assembly group mando"),
                # A matched but incomplete repair remains pending.
                ("F", "2026-09-01 13:00", "Audio-Testing", "F-F", "SMT equipment"),
                # Explicitly outside both validated classifications.
                ("G", "2026-09-01 14:00", "Aging-Software-Testing", "F-G", "Dayshift assembly group mando"),
            ]
            defect_rows = []
            for pcb, timestamp, operation, phenomenon, duty in events:
                defect_rows.append(
                    {
                        "PCB": pcb,
                        "BadMachEntryTime": timestamp,
                        "TestTime": timestamp,
                        "TestOperation": operation,
                        "Fault Phenomenon": phenomenon,
                        "DutyType": duty,
                        "model": "M1",
                    }
                )
            defects = root / "defects.xlsx"
            self.write_book(defects, "Detail", pd.DataFrame(defect_rows))

            repairs = root / "repair.xlsx"
            repair_rows = []
            for pcb, duty, repair_date in (
                ("D", "Dayshift assembly group mando", "2026-09-03 08:00"),
                ("E", "SMT Mando", "2026-09-03 09:00"),
                ("F", "", ""),
            ):
                event = next(row for row in defect_rows if row["PCB"] == pcb)
                repair_rows.append(
                    {
                        "PCB": pcb,
                        "TestTime": event["TestTime"],
                        "TestOperation": event["TestOperation"],
                        "Fault Phenomenon": event["Fault Phenomenon"],
                        "DutyType": duty,
                        "RepairDate": repair_date,
                    }
                )
            self.write_book(repairs, "QueryData", pd.DataFrame(repair_rows))

            result = assembly_kpi_v2.calculate(
                input_paths, defects, repairs, date(2026, 9, 1), date(2026, 9, 2)
            )

            self.assertEqual(result["produced"], 200)
            self.assertEqual(result["functional_pcbs"], 5)
            self.assertEqual(result["appearance_pcbs"], 1)
            self.assertEqual(result["function_mando_pcbs"], 3)  # A, C and D
            self.assertEqual(result["smt_duty_pcbs"], 1)  # E only
            self.assertEqual(result["pending_responsibility_pcbs"], 1)  # F
            self.assertEqual(result["daily"]["FunctionalNGPCBs"].sum(), 6)
            self.assertEqual(result["functional_pcbs"], 5)
            self.assertEqual(len(result["unclassified"]), 1)

    def test_rejects_period_input_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "period-input.xlsx"
            self.write_book(
                path,
                "ModelData",
                pd.DataFrame(
                    [{"model": "M1", "Input": 200, "BeginDate": "2026-09-01", "EndDate": "2026-09-02"}]
                ),
            )
            with self.assertRaisesRegex(RuntimeError, "somente inputs diários"):
                assembly_kpi_v2.read_daily_input(path)


class SMTValidatedRulesTest(unittest.TestCase):
    def test_fpy_detail_is_authoritative_and_uses_entry_date(self) -> None:
        detail = pd.DataFrame(
            [
                {
                    "PCB": "PCB-1",
                    "model": "M1",
                    "BadMachEntryTime": "2026-09-02 08:00",
                    "TestTime": "2026-08-10 08:00",
                    "TestOperation": "Download",
                    "Fault Phenomenon": "Functional",
                    "DutyType": "SMT Mando",
                    "Maintenance": "Re-Judge OK",
                    "RepairerRemark": "Retest OK",
                },
                {
                    "PCB": "PCB-2",
                    "model": "M1",
                    "BadMachEntryTime": "2026-09-02 09:00",
                    "TestTime": "",
                    "TestOperation": "SMT-Visual-Inspection",
                    "Fault Phenomenon": "Appearance",
                    "DutyType": "SMT Mando",
                },
            ]
        )
        summary = pd.DataFrame(
            [{"OnceDamage": 2, "2TimesDamage": 0, "3TimesDamage": 0, "4TimesDamage": 0, "5TimesDamage": 0, "6TimesDamage": 0}]
        )
        payload = BytesIO()
        with pd.ExcelWriter(payload, engine="openpyxl") as writer:
            detail.to_excel(writer, sheet_name="Detail", index=False)
            summary.to_excel(writer, sheet_name="BadMachine", index=False)
        payload.seek(0)

        result, audit = smt_quality_dashboard.read_defect_bytes(payload.read(), "fpy.xlsx")

        self.assertEqual(result["ValidDefect"].sum(), 2)
        self.assertFalse(result["IsRejudgeOK"].any())
        self.assertEqual(set(result["FailureType"]), {"Functional Failure", "Appearance Failure"})
        self.assertEqual(set(result["KPIDate"].dt.strftime("%Y-%m-%d")), {"2026-09-02"})
        self.assertEqual(audit["SMTMando"], 2)


if __name__ == "__main__":
    unittest.main()
