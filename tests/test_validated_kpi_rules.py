import tempfile
import unittest
import sys
import types
from datetime import date
from io import BytesIO
from pathlib import Path

import pandas as pd


try:
    import streamlit  # noqa: F401
except ModuleNotFoundError:
    def _identity_cache(*args, **kwargs):
        def decorator(function):
            return function

        return decorator

    streamlit_stub = types.ModuleType("streamlit")
    streamlit_stub.cache_data = _identity_cache
    streamlit_stub.cache_resource = _identity_cache
    streamlit_stub.secrets = {}
    sys.modules["streamlit"] = streamlit_stub

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

    def test_september_mes_operation_mapping(self) -> None:
        """Keep the operation names reconciled with the validated 14–15 September FPY extracts."""
        self.assertTrue(assembly_kpi_v2.ASSEMBLY_KPI_RULE_VERSION)
        self.assertIn("Camera-auxiliary-tester", assembly_kpi_v2.FUNCTIONAL_OPERATIONS)
        self.assertIn("Glue_dispensing", assembly_kpi_v2.APPEARANCE_OPERATIONS)
        self.assertIn("PCB-Assembly", assembly_kpi_v2.APPEARANCE_OPERATIONS)

    def test_archived_fpy_monthly_snapshots_are_combined(self) -> None:
        """An August snapshot must remain available after a September snapshot is uploaded."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "input-aug.xlsx"
            self.write_book(
                input_path,
                "ModelData",
                pd.DataFrame([{"model": "M1", "Input": 100, "BeginDate": "2026-08-10", "EndDate": "2026-08-10"}]),
            )
            august_defects = root / "defects-aug.xlsx"
            self.write_book(
                august_defects,
                "Detail",
                pd.DataFrame([{
                    "PCB": "AUG-SMT-1", "BadMachEntryTime": "2026-08-10 08:00", "TestTime": "2026-08-10 08:00",
                    "TestOperation": "Audio-Testing", "Fault Phenomenon": "Failure", "DutyType": "SMT Process", "model": "M1",
                }]),
            )
            september_defects = root / "defects-sep.xlsx"
            self.write_book(
                september_defects,
                "Detail",
                pd.DataFrame([{
                    "PCB": "SEP-1", "BadMachEntryTime": "2026-09-01 08:00", "TestTime": "2026-09-01 08:00",
                    "TestOperation": "Audio-Testing", "Fault Phenomenon": "Failure", "DutyType": "Dayshift assembly group mando", "model": "M1",
                }]),
            )
            repair_path = root / "repair.xlsx"
            self.write_book(
                repair_path,
                "QueryData",
                pd.DataFrame([{
                    "PCB": "UNRELATED", "TestTime": "2026-09-02 08:00", "TestOperation": "Audio-Testing",
                    "Fault Phenomenon": "Failure", "DutyType": "", "RepairDate": "",
                }]),
            )

            result = assembly_kpi_v2.calculate(
                [input_path], [august_defects, september_defects], repair_path, date(2026, 8, 1), date(2026, 8, 31)
            )
            self.assertEqual(result["smt_duty_pcbs"], 1)
            self.assertEqual(result["smt_duty_ppm"], 10_000)

    def test_partial_repair_upload_keeps_prior_event_classifications(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "input.xlsx"
            self.write_book(
                input_path, "ModelData",
                pd.DataFrame([{"model": "M1", "Input": 100, "BeginDate": "2026-08-10", "EndDate": "2026-08-10"}]),
            )
            defect_path = root / "defects.xlsx"
            self.write_book(
                defect_path, "Detail",
                pd.DataFrame([{
                    "PCB": "AUG-1", "BadMachEntryTime": "2026-08-10 08:00", "TestTime": "2026-08-10 08:00",
                    "TestOperation": "Audio-Testing", "Fault Phenomenon": "Failure", "DutyType": "SMT Process", "model": "M1",
                }]),
            )
            first_repair = root / "repair-first.xlsx"
            self.write_book(
                first_repair, "QueryData",
                pd.DataFrame([{
                    "PCB": "AUG-1", "TestTime": "2026-08-10 08:00", "TestOperation": "Audio-Testing",
                    "Fault Phenomenon": "Failure", "DutyType": "Dayshift assembly group mando", "RepairDate": "2026-08-11 08:00",
                }]),
            )
            second_repair = root / "repair-partial.xlsx"
            self.write_book(
                second_repair, "QueryData",
                pd.DataFrame([{
                    "PCB": "OTHER", "TestTime": "2026-08-12 08:00", "TestOperation": "Audio-Testing",
                    "Fault Phenomenon": "Failure", "DutyType": "SMT Process", "RepairDate": "2026-08-12 08:00",
                }]),
            )

            result = assembly_kpi_v2.calculate(
                [input_path], defect_path, [first_repair, second_repair], date(2026, 8, 1), date(2026, 8, 31)
            )
            self.assertEqual(result["smt_duty_pcbs"], 0)
            self.assertEqual(result["function_mando_pcbs"], 1)


class SMTValidatedRulesTest(unittest.TestCase):
    def test_weekly_trend_boundaries_stay_inside_selected_period(self) -> None:
        first_week = pd.Timestamp("2026-08-01").to_period("W-SUN")
        first_begin, first_end = smt_quality_dashboard.clipped_trend_period_bounds(
            first_week,
            "week",
            pd.Timestamp("2026-08-01"),
            pd.Timestamp("2026-09-01"),
        )
        self.assertEqual(first_begin, pd.Timestamp("2026-08-01"))
        self.assertEqual(first_end, pd.Timestamp("2026-08-03"))

        last_week = pd.Timestamp("2026-08-31").to_period("W-SUN")
        last_begin, last_end = smt_quality_dashboard.clipped_trend_period_bounds(
            last_week,
            "week",
            pd.Timestamp("2026-08-01"),
            pd.Timestamp("2026-09-01"),
        )
        self.assertEqual(last_begin, pd.Timestamp("2026-08-31"))
        self.assertEqual(last_end, pd.Timestamp("2026-09-01"))

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
