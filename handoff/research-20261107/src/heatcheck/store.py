"""SQLite persistence. Public and restricted tables live in separate database files so that
file-system permissions (or a separate process owned by Max) can gate the restricted one.
Isolation is LOGICAL ONLY until such permissions are applied (Research §06)."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pandas as pd


def _to_sql_frame(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    for c in d.columns:
        if isinstance(d[c].dtype, pd.DatetimeTZDtype):
            d[c] = d[c].dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        elif d[c].dtype == bool:
            d[c] = d[c].astype(int)
    return d


def publish(db_path: Path, tables: dict[str, pd.DataFrame], restricted: bool = False) -> None:
    """Write all tables in ONE transaction to a temp file, then atomically rename."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    try:
        con.execute("BEGIN")
        for name, df in tables.items():
            _to_sql_frame(df).to_sql(name, con, index=False)
        con.commit()
    except Exception:
        con.rollback(); con.close(); tmp.unlink(missing_ok=True); raise
    con.close()
    os.replace(tmp, db_path)
    if restricted:
        os.chmod(db_path, 0o600)


def read(db_path: Path, table: str) -> pd.DataFrame:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return pd.read_sql(f"SELECT * FROM {table}", con)
    finally:
        con.close()
