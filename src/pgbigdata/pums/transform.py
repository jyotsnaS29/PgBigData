"""Pure transform: a raw PUMS API row -> a storable person record.

No I/O — unit-tested in tests/test_pums_transform.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .variables import DATA_COLUMNS, KEY, coerce_int, coerce_text


@dataclass
class PumsRecord:
    dataset: str
    year: int
    serialno: str
    sporder: int
    st: str
    promoted: dict[str, Any]   # typed columns (excl. key + st)
    raw: dict[str, str]        # full payload -> JSONB


def _coerce(var, row: dict[str, str]):
    val = row.get(var.code)
    return coerce_int(val) if var.numeric else coerce_text(val)


def transform_row(row: dict[str, str], *, dataset: str, year: int) -> PumsRecord:
    promoted = {var.column: _coerce(var, row) for var in DATA_COLUMNS}
    return PumsRecord(
        dataset=dataset,
        year=year,
        serialno=row["SERIALNO"],
        sporder=coerce_int(row.get("SPORDER")) or 0,
        st=row.get("state", ""),   # 'state' is the for=state response column
        promoted=promoted,
        raw=row,
    )


def record_as_db_params(rec: PumsRecord) -> dict[str, Any]:
    params: dict[str, Any] = {
        "dataset": rec.dataset,
        "year": rec.year,
        "serialno": rec.serialno,
        "sporder": rec.sporder,
        "st": rec.st,
        "raw": rec.raw,
    }
    params.update(rec.promoted)
    return params


# Column order for the upsert (must match sql/003_pums.sql).
INSERT_COLUMNS = (
    ["dataset", "year", "serialno", "sporder", "st"]
    + [v.column for v in DATA_COLUMNS]
    + ["raw"]
)
KEY_COLUMNS = ["dataset", "year", "serialno", "sporder"]
_ = KEY  # re-exported for callers/tests that want the key var metadata
