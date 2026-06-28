"""Idempotent CCES upsert into cces_response, keyed on (year, caseid).

Reuses the run-tracking + batching helpers from the aggregate loader.
"""
from __future__ import annotations

import logging
from typing import Iterable

import psycopg
from psycopg.types.json import Jsonb

from ..census.loader import BATCH_SIZE, _batched, _finish_run, _start_run
from .transform import CONFLICT_COLUMNS, INSERT_COLUMNS, CcesRecord, record_as_db_params

log = logging.getLogger(__name__)


def _build_upsert() -> str:
    cols = ", ".join(INSERT_COLUMNS)
    placeholders = ", ".join(f"%({c})s" for c in INSERT_COLUMNS)
    conflict = ", ".join(CONFLICT_COLUMNS)
    updatable = [c for c in INSERT_COLUMNS if c not in CONFLICT_COLUMNS]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in updatable)
    return (
        f"INSERT INTO cces_response ({cols}, updated_at) "
        f"VALUES ({placeholders}, now()) "
        f"ON CONFLICT ({conflict}) DO UPDATE SET {set_clause}, updated_at = now()"
    )


UPSERT_SQL = _build_upsert()


def load(
    conn: psycopg.Connection,
    records: Iterable[CcesRecord],
    *,
    dataset: str,
    year: int,
    geography: str,
) -> int:
    run_id = _start_run(conn, dataset, year, geography)
    conn.commit()
    total = 0
    try:
        with conn.cursor() as cur:
            for batch in _batched(records, BATCH_SIZE):
                params = []
                for rec in batch:
                    if rec.caseid is None:
                        continue  # skip malformed rows without a key
                    p = record_as_db_params(rec)
                    p["raw"] = Jsonb(p["raw"])
                    params.append(p)
                if params:
                    cur.executemany(UPSERT_SQL, params)
                    total += len(params)
                    conn.commit()
                    log.info("upserted %d respondents (running total %d)", len(params), total)
        _finish_run(conn, run_id, "success", total, None)
        conn.commit()
        return total
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        _finish_run(conn, run_id, "failed", total, str(exc)[:500])
        conn.commit()
        raise
