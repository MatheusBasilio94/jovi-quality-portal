"""One-time historical OQC/FQC archive transcribed from FQC&OQC.xlsx."""

from datetime import datetime
import sqlite3

ARCHIVE_VERSION = "oqc-fqc-history-2026-09-16.1"

SMT_OQC_RECORDS = [
    ('2026-07-27', 21, 0),
    ('2026-07-28', 23, 0),
    ('2026-07-29', 24, 0),
    ('2026-07-30', 28, 0),
    ('2026-07-31', 28, 0),
    ('2026-08-03', 39, 0),
    ('2026-08-04', 24, 0),
    ('2026-08-05', 47, 0),
    ('2026-08-06', 52, 0),
    ('2026-08-07', 28, 0),
    ('2026-08-08', 16, 0),
    ('2026-08-10', 23, 0),
    ('2026-08-11', 24, 0),
    ('2026-08-12', 26, 0),
    ('2026-08-13', 63, 0),
    ('2026-08-14', 54, 1),
    ('2026-08-17', 51, 0),
    ('2026-08-18', 53, 1),
    ('2026-08-19', 63, 1),
    ('2026-08-21', 32, 0),
    ('2026-08-22', 25, 0),
    ('2026-08-24', 28, 0),
    ('2026-08-25', 72, 0),
    ('2026-08-26', 89, 0),
    ('2026-08-27', 33, 0),
    ('2026-08-28', 50, 0),
    ('2026-08-29', 4, 0),
    ('2026-08-31', 64, 0),
    ('2026-09-01', 50, 0),
    ('2026-09-02', 39, 1),
    ('2026-09-03', 36, 0),
    ('2026-09-04', 41, 0),
    ('2026-09-08', 50, 0),
    ('2026-09-09', 48, 0),
    ('2026-09-10', 37, 0),
    ('2026-09-11', 21, 1),
    ('2026-09-14', 2, 0),
    ('2026-09-15', 2, 0),
]

ASSEMBLY_OQC_FQC_RECORDS = [
    ('2026-07-27', 6, 0, 20, 0),
    ('2026-07-28', 6, 0, 20, 0),
    ('2026-07-29', 4, 0, 20, 0),
    ('2026-07-30', 2, 0, 20, 0),
    ('2026-07-31', 5, 1, 18, 0),
    ('2026-08-03', 6, 0, 20, 0),
    ('2026-08-04', 12, 2, 20, 0),
    ('2026-08-05', 10, 0, 20, 0),
    ('2026-08-06', 8, 0, 20, 0),
    ('2026-08-07', 4, 0, 18, 0),
    ('2026-08-10', 13, 0, 20, 0),
    ('2026-08-11', 24, 1, 20, 1),
    ('2026-08-12', 9, 0, 20, 0),
    ('2026-08-13', 8, 0, 30, 0),
    ('2026-08-14', 6, 0, 22, 0),
    ('2026-08-17', 12, 0, 34, 2),
    ('2026-08-18', 14, 0, 32, 0),
    ('2026-08-19', 12, 0, 20, 0),
    ('2026-08-20', 8, 0, 22, 0),
    ('2026-08-21', 14, 0, 28, 0),
    ('2026-08-24', 14, 0, 32, 0),
    ('2026-08-25', 19, 0, 34, 0),
    ('2026-08-26', 20, 0, 34, 0),
    ('2026-08-27', 14, 0, 34, 0),
    ('2026-08-28', 15, 0, 30, 0),
    ('2026-08-31', 18, 0, 28, 1),
    ('2026-09-01', 15, 0, 34, 0),
    ('2026-09-02', 8, 0, 34, 0),
    ('2026-09-03', 16, 0, 34, 0),
    ('2026-09-04', 16, 0, 30, 1),
    ('2026-09-08', 7, 0, 34, 0),
    ('2026-09-09', 12, 0, 34, 1),
    ('2026-09-10', 8, 0, 28, 0),
    ('2026-09-11', 2, 0, 30, 0),
    ('2026-09-14', 12, 0, 30, 0),
    ('2026-09-15', 20, 0, 28, 0),
]


def apply_archive(conn: sqlite3.Connection) -> bool:
    """Replace the archive period once and record that the import completed."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS portal_data_migrations (
            migration_key TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    already_applied = conn.execute(
        "SELECT 1 FROM portal_data_migrations WHERE migration_key = ?",
        (ARCHIVE_VERSION,),
    ).fetchone()
    if already_applied:
        return False

    start_date = min(SMT_OQC_RECORDS[0][0], ASSEMBLY_OQC_FQC_RECORDS[0][0])
    end_date = max(SMT_OQC_RECORDS[-1][0], ASSEMBLY_OQC_FQC_RECORDS[-1][0])
    note = "Imported from FQC&OQC.xlsx historical archive"
    imported_at = datetime.now().isoformat(timespec="seconds")

    conn.execute(
        "DELETE FROM smt_oqc_inspections WHERE inspection_date BETWEEN ? AND ?",
        (start_date, end_date),
    )
    conn.execute(
        "DELETE FROM assembly_oqc_fqc_inspections WHERE inspection_date BETWEEN ? AND ?",
        (start_date, end_date),
    )
    conn.executemany(
        """
        INSERT INTO smt_oqc_inspections
            (inspection_date, model, inspected_qty, ok_qty, ng_qty, notes, created_at)
        VALUES (?, NULL, ?, ?, ?, ?, ?)
        """,
        [
            (day, inspected, inspected - failed, failed, note, imported_at)
            for day, inspected, failed in SMT_OQC_RECORDS
        ],
    )
    conn.executemany(
        """
        INSERT INTO assembly_oqc_fqc_inspections
            (inspection_date, model, oqc_inspected_qty, oqc_ok_qty, oqc_ng_qty,
             fqc_inspected_qty, fqc_ok_qty, fqc_ng_qty, notes, created_at)
        VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                day,
                oqc_inspected,
                oqc_inspected - oqc_failed,
                oqc_failed,
                fqc_inspected,
                fqc_inspected - fqc_failed,
                fqc_failed,
                note,
                imported_at,
            )
            for day, oqc_inspected, oqc_failed, fqc_inspected, fqc_failed in ASSEMBLY_OQC_FQC_RECORDS
        ],
    )
    conn.execute(
        "INSERT INTO portal_data_migrations (migration_key, applied_at) VALUES (?, ?)",
        (ARCHIVE_VERSION, imported_at),
    )
    return True
