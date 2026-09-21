"""Storage rules for manual SMT OQC and Assembly OQC/FQC inspection records."""

from __future__ import annotations

import sqlite3


SMT_OQC_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS smt_oqc_inspections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inspection_date TEXT NOT NULL,
        model TEXT,
        inspected_qty INTEGER NOT NULL CHECK (inspected_qty >= 0),
        ok_qty INTEGER NOT NULL CHECK (ok_qty >= 0),
        ng_qty INTEGER NOT NULL CHECK (ng_qty >= 0),
        notes TEXT,
        created_at TEXT NOT NULL,
        CHECK (ok_qty + ng_qty = inspected_qty)
    )
"""

ASSEMBLY_OQC_FQC_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS assembly_oqc_fqc_inspections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inspection_date TEXT NOT NULL,
        model TEXT,
        oqc_inspected_qty INTEGER NOT NULL CHECK (oqc_inspected_qty >= 0),
        oqc_ok_qty INTEGER NOT NULL CHECK (oqc_ok_qty >= 0),
        oqc_ng_qty INTEGER NOT NULL CHECK (oqc_ng_qty >= 0),
        fqc_inspected_qty INTEGER NOT NULL CHECK (fqc_inspected_qty >= 0),
        fqc_ok_qty INTEGER NOT NULL CHECK (fqc_ok_qty >= 0),
        fqc_ng_qty INTEGER NOT NULL CHECK (fqc_ng_qty >= 0),
        notes TEXT,
        created_at TEXT NOT NULL,
        CHECK (oqc_ok_qty + oqc_ng_qty = oqc_inspected_qty),
        CHECK (fqc_ok_qty + fqc_ng_qty = fqc_inspected_qty)
    )
"""


def create_inspection_tables(conn: sqlite3.Connection) -> None:
    conn.execute(SMT_OQC_TABLE_SQL)
    conn.execute(ASSEMBLY_OQC_FQC_TABLE_SQL)


def migrate_zero_sampling_schema(conn: sqlite3.Connection) -> bool:
    """Allow zero-inspection records in databases created before this rule."""
    migrations = (
        (
            "smt_oqc_inspections",
            "inspected_qty > 0",
            SMT_OQC_TABLE_SQL,
            "id, inspection_date, model, inspected_qty, ok_qty, ng_qty, notes, created_at",
        ),
        (
            "assembly_oqc_fqc_inspections",
            "oqc_inspected_qty > 0",
            ASSEMBLY_OQC_FQC_TABLE_SQL,
            (
                "id, inspection_date, model, oqc_inspected_qty, oqc_ok_qty, oqc_ng_qty, "
                "fqc_inspected_qty, fqc_ok_qty, fqc_ng_qty, notes, created_at"
            ),
        ),
    )
    migrated = False
    for table_name, legacy_constraint, create_sql, columns in migrations:
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)
        ).fetchone()
        if not sql or legacy_constraint not in str(sql[0]).lower():
            continue
        legacy_name = f"{table_name}_pre_zero_sampling"
        conn.execute(f"ALTER TABLE {table_name} RENAME TO {legacy_name}")
        conn.execute(create_sql)
        conn.execute(f"INSERT INTO {table_name} ({columns}) SELECT {columns} FROM {legacy_name}")
        conn.execute(f"DROP TABLE {legacy_name}")
        migrated = True
    return migrated


def validate_inspection_counts(stage: str, inspected_qty: int, ok_qty: int, ng_qty: int) -> None:
    """Validate a sampled or explicitly unsampled OQC/FQC record."""
    if inspected_qty < 0:
        raise ValueError(f"{stage} inspected quantity cannot be negative.")
    if ok_qty < 0 or ng_qty < 0:
        raise ValueError(f"{stage} OK and NG quantities cannot be negative.")
    if ok_qty + ng_qty != inspected_qty:
        raise ValueError(f"{stage} OK quantity plus NG quantity must equal the inspected quantity.")
