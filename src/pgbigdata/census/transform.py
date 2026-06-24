"""Turn a raw API row into a storable record.

The transform is a *pure function* (no I/O) so it can be unit-tested without a
database or network — see tests/test_transform.py. It produces both halves of
the storage model: the promoted typed columns and the full raw JSONB payload.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .geography import Geography, build_geoid
from .variables import PROMOTED, coerce_numeric


@dataclass
class AcsRecord:
    dataset: str
    year: int
    geography: str
    geoid: str
    name: str | None
    promoted: dict[str, int | None]  # typed columns
    raw: dict[str, str]              # full payload -> JSONB


def transform_row(
    row: dict[str, str], *, dataset: str, year: int, geo: Geography
) -> AcsRecord:
    geoid = build_geoid(geo, row)
    promoted = {
        var.column: coerce_numeric(row.get(var.code)) for var in PROMOTED
    }
    return AcsRecord(
        dataset=dataset,
        year=year,
        geography=geo.name,
        geoid=geoid,
        name=row.get("NAME"),
        promoted=promoted,
        raw=row,
    )


def record_as_db_params(rec: AcsRecord) -> dict[str, Any]:
    """Flatten an AcsRecord into the parameter dict the upsert expects."""
    params: dict[str, Any] = {
        "dataset": rec.dataset,
        "year": rec.year,
        "geography": rec.geography,
        "geoid": rec.geoid,
        "name": rec.name,
        "raw": rec.raw,
    }
    params.update(rec.promoted)
    return params
