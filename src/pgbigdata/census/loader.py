"""Idempotent, incremental loader.

Idempotency: every record upserts on the natural key (dataset, year, geography,
geoid). Re-running a load updates rows in place rather than duplicating them.

Incrementality: each run is recorded in `load_runs` with its parameters and a
checksum-free status. The CLI skips a (dataset, year, geography) that already
has a successful run unless --force is passed, so a daily job is cheap and only
new vintages do real work.

Throughput: records are upserted in batches with psycopg's executemany over a
prepared statement, and the JSONB payload is adapted via Jsonb().
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable, Iterator

import psycopg
from psycopg.types.json import Jsonb

from .transform import AcsRecord, record_as_db_params
from .variables import PROMOTED

log = logging.getLogger(__name__)

BATCH_SIZE = 500

_PROMOTED_COLS = [v.column for v in PROMOTED]
_INSERT_COLS = ["dataset", "year", "geography", "geoid", "name", *_PROMOTED_COLS, "raw"]


def _build_upsert() -> str:
    cols = ", ".join(_INSERT_COLS)
    placeholders = ", ".join(f"%({c})s" for c in _INSERT_COLS)
    # On conflict, refresh every non-key column (incl. raw payload).
    updatable = [c for c in _INSERT_COLS if c not in ("dataset", "year", "geography", "geoid")]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in updatable)
    return (
        f"INSERT INTO acs_observations ({cols}, updated_at) "
        f"VALUES ({placeholders}, now()) "
        f"ON CONFLICT (dataset, year, geography, geoid) DO UPDATE SET "
        f"{set_clause}, updated_at = now()"
    )


UPSERT_SQL = _build_upsert()


def already_loaded(conn: psycopg.Connection, dataset: str, year: int, geography: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM load_runs "
            "WHERE dataset=%s AND year=%s AND geography=%s AND status='success' "
            "LIMIT 1",
            (dataset, year, geography),
        )
        return cur.fetchone() is not None


def _start_run(conn: psycopg.Connection, dataset: str, year: int, geography: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO load_runs (dataset, year, geography, status, started_at) "
            "VALUES (%s, %s, %s, 'running', %s) RETURNING id",
            (dataset, year, geography, datetime.now(timezone.utc)),
        )
        return cur.fetchone()["id"]


def _finish_run(conn: psycopg.Connection, run_id: int, status: str, rows: int, error: str | None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE load_runs SET status=%s, row_count=%s, error=%s, finished_at=%s WHERE id=%s",
            (status, rows, error, datetime.now(timezone.utc), run_id),
        )


def _batched(items: Iterable[AcsRecord], size: int) -> Iterator[list[AcsRecord]]:
    batch: list[AcsRecord] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def load(
    conn: psycopg.Connection,
    records: Iterable[AcsRecord],
    *,
    dataset: str,
    year: int,
    geography: str,
) -> int:
    """Upsert records in batches inside a tracked load run. Returns row count."""
    run_id = _start_run(conn, dataset, year, geography)
    conn.commit()  # make the 'running' marker durable immediately
    total = 0
    try:
        with conn.cursor() as cur:
            for batch in _batched(records, BATCH_SIZE):
                params = []
                for rec in batch:
                    p = record_as_db_params(rec)
                    p["raw"] = Jsonb(p["raw"])  # adapt dict -> jsonb
                    params.append(p)
                cur.executemany(UPSERT_SQL, params)
                total += len(batch)
                conn.commit()  # commit per batch -> resumable, bounded txn size
                log.info("upserted %d rows (running total %d)", len(batch), total)
        _finish_run(conn, run_id, "success", total, None)
        conn.commit()
        return total
    except Exception as exc:  # noqa: BLE001 — record failure durably, then re-raise
        conn.rollback()  # drop the partial batch that errored
        _finish_run(conn, run_id, "failed", total, str(exc)[:500])
        conn.commit()
        raise
