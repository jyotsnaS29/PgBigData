"""Pure transform: a CCES respondent row -> a storable record. Unit-tested."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .variables import KEY, PROMOTED, coerce


@dataclass
class CcesRecord:
    dataset: str
    year: int
    caseid: int | None
    promoted: dict[str, Any]
    raw: dict[str, str]


def transform_row(row: dict[str, str], *, dataset: str, year: int) -> CcesRecord:
    promoted = {v.col: coerce(v.kind, row.get(v.col)) for v in PROMOTED}
    return CcesRecord(
        dataset=dataset,
        year=year,
        caseid=coerce(KEY.kind, row.get(KEY.col)),
        promoted=promoted,
        raw=row,
    )


def record_as_db_params(rec: CcesRecord) -> dict[str, Any]:
    params: dict[str, Any] = {
        "dataset": rec.dataset,
        "year": rec.year,
        "caseid": rec.caseid,
        "raw": rec.raw,
    }
    params.update(rec.promoted)
    return params


INSERT_COLUMNS = ["dataset", "year", "caseid"] + [v.col for v in PROMOTED] + ["raw"]
CONFLICT_COLUMNS = ["year", "caseid"]
