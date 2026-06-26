"""Idempotent PUMS upsert. Reuses the run-tracking + batching helpers from the
aggregate loader; only the target table and conflict key differ.

Idempotency key: (dataset, year, serialno, sporder) — one person record.
"""
from __future__ import annotations

import logging
from typing import Iterable

import psycopg
from psycopg.types.json import Jsonb

from ..census.loader import BATCH_SIZE, _batched, _finish_run, _start_run
from .transform import INSERT_COLUMNS, KEY_COLUMNS, PumsRecord, record_as_db_params

log = logging.getLogger(__name__)


def _build_upsert() -> str:
    cols = ", ".join(INSERT_COLUMNS)
    placeholders = ", ".join(f"%({c})s" for c in INSERT_COLUMNS)
    updatable = [c for c in INSERT_COLUMNS if c not in KEY_COLUMNS]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in updatable)
    return (
        f"INSERT INTO pums_person ({cols}, updated_at) "
        f"VALUES ({placeholders}, now()) "
        f"ON CONFLICT (dataset, year, serialno, sporder) DO UPDATE SET "
        f"{set_clause}, updated_at = now()"
    )


UPSERT_SQL = _build_upsert()


def load(
    conn: psycopg.Connection,
    records: Iterable[PumsRecord],
    *,
    dataset: str,
    year: int,
    geography: str,
) -> int:
    """Upsert PUMS person records in batches inside a tracked run."""
    run_id = _start_run(conn, dataset, year, geography)
    conn.commit()
    total = 0
    try:
        with conn.cursor() as cur:
            for batch in _batched(records, BATCH_SIZE):
                params = []
                for rec in batch:
                    p = record_as_db_params(rec)
                    p["raw"] = Jsonb(p["raw"])
                    params.append(p)
                cur.executemany(UPSERT_SQL, params)
                total += len(batch)
                conn.commit()
                log.info("upserted %d person rows (running total %d)", len(batch), total)
        _finish_run(conn, run_id, "success", total, None)
        conn.commit()
        return total
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        _finish_run(conn, run_id, "failed", total, str(exc)[:500])
        conn.commit()
        raise
