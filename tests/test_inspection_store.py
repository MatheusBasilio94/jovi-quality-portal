import sqlite3
import unittest

from tools.inspection_store import (
    create_inspection_tables,
    migrate_zero_sampling_schema,
    validate_inspection_counts,
)


class InspectionStoreTests(unittest.TestCase):
    def test_zero_sampling_is_valid_only_when_ok_and_ng_are_zero(self):
        validate_inspection_counts("SMT OQC", 0, 0, 0)
        with self.assertRaises(ValueError):
            validate_inspection_counts("SMT OQC", 0, 1, 0)

    def test_legacy_database_migrates_without_losing_records(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.executescript(
            """
            CREATE TABLE smt_oqc_inspections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inspection_date TEXT NOT NULL, model TEXT,
                inspected_qty INTEGER NOT NULL CHECK (inspected_qty > 0),
                ok_qty INTEGER NOT NULL CHECK (ok_qty >= 0),
                ng_qty INTEGER NOT NULL CHECK (ng_qty >= 0),
                notes TEXT, created_at TEXT NOT NULL,
                CHECK (ok_qty + ng_qty = inspected_qty)
            );
            CREATE TABLE assembly_oqc_fqc_inspections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inspection_date TEXT NOT NULL, model TEXT,
                oqc_inspected_qty INTEGER NOT NULL CHECK (oqc_inspected_qty > 0),
                oqc_ok_qty INTEGER NOT NULL CHECK (oqc_ok_qty >= 0),
                oqc_ng_qty INTEGER NOT NULL CHECK (oqc_ng_qty >= 0),
                fqc_inspected_qty INTEGER NOT NULL CHECK (fqc_inspected_qty > 0),
                fqc_ok_qty INTEGER NOT NULL CHECK (fqc_ok_qty >= 0),
                fqc_ng_qty INTEGER NOT NULL CHECK (fqc_ng_qty >= 0),
                notes TEXT, created_at TEXT NOT NULL,
                CHECK (oqc_ok_qty + oqc_ng_qty = oqc_inspected_qty),
                CHECK (fqc_ok_qty + fqc_ng_qty = fqc_inspected_qty)
            );
            INSERT INTO smt_oqc_inspections
                (inspection_date, model, inspected_qty, ok_qty, ng_qty, notes, created_at)
            VALUES ('2026-09-20', 'PD', 10, 9, 1, '', '2026-09-20T10:00:00');
            """
        )

        self.assertTrue(migrate_zero_sampling_schema(conn))
        create_inspection_tables(conn)
        conn.execute(
            """INSERT INTO smt_oqc_inspections
            (inspection_date, model, inspected_qty, ok_qty, ng_qty, notes, created_at)
            VALUES ('2026-09-21', '', 0, 0, 0, 'No sampling', '2026-09-21T10:00:00')"""
        )
        conn.execute(
            """INSERT INTO assembly_oqc_fqc_inspections
            (inspection_date, model, oqc_inspected_qty, oqc_ok_qty, oqc_ng_qty,
             fqc_inspected_qty, fqc_ok_qty, fqc_ng_qty, notes, created_at)
            VALUES ('2026-09-21', '', 0, 0, 0, 0, 0, 0, 'No sampling', '2026-09-21T10:00:00')"""
        )
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM smt_oqc_inspections").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT inspected_qty FROM smt_oqc_inspections WHERE id = 1").fetchone()[0], 10)


if __name__ == "__main__":
    unittest.main()
