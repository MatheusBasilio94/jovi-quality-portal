import sqlite3
import unittest

from tools.historical_inspection_archive import (
    ARCHIVE_VERSION,
    ASSEMBLY_OQC_FQC_RECORDS,
    SMT_OQC_RECORDS,
    apply_archive,
)


class HistoricalInspectionArchiveTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript(
            """
            CREATE TABLE smt_oqc_inspections (
                id INTEGER PRIMARY KEY,
                inspection_date TEXT NOT NULL,
                model TEXT,
                inspected_qty INTEGER NOT NULL,
                ok_qty INTEGER NOT NULL,
                ng_qty INTEGER NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE assembly_oqc_fqc_inspections (
                id INTEGER PRIMARY KEY,
                inspection_date TEXT NOT NULL,
                model TEXT,
                oqc_inspected_qty INTEGER NOT NULL,
                oqc_ok_qty INTEGER NOT NULL,
                oqc_ng_qty INTEGER NOT NULL,
                fqc_inspected_qty INTEGER NOT NULL,
                fqc_ok_qty INTEGER NOT NULL,
                fqc_ng_qty INTEGER NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL
            );
            """
        )

    def tearDown(self):
        self.conn.close()

    def test_imports_once_without_duplicate_records(self):
        self.assertTrue(apply_archive(self.conn))
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM smt_oqc_inspections").fetchone()[0],
            len(SMT_OQC_RECORDS),
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM assembly_oqc_fqc_inspections").fetchone()[0],
            len(ASSEMBLY_OQC_FQC_RECORDS),
        )
        self.assertEqual(
            self.conn.execute("SELECT SUM(inspected_qty), SUM(ng_qty) FROM smt_oqc_inspections").fetchone(),
            (1410, 5),
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT SUM(oqc_inspected_qty), SUM(oqc_ng_qty), SUM(fqc_inspected_qty), SUM(fqc_ng_qty) "
                "FROM assembly_oqc_fqc_inspections"
            ).fetchone(),
            (399, 4, 952, 6),
        )
        self.assertFalse(apply_archive(self.conn))
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM portal_data_migrations WHERE migration_key = ?", (ARCHIVE_VERSION,)).fetchone()[0],
            1,
        )


if __name__ == "__main__":
    unittest.main()
