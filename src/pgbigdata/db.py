"""Thin Postgres helpers built on psycopg 3.

Deliberately no ORM: the JSONB/typed-column modeling and indexing this project
is about are clearest in plain SQL, and bulk upserts via execute_values-style
batching are the performance-sensitive path.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

log = logging.getLogger(__name__)


@contextmanager
def connect(database_url: str) -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(database_url, row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run_sql_file(conn: psycopg.Connection, path: str | Path) -> None:
    sql = Path(path).read_text()
    log.info("applying %s", path)
    with conn.cursor() as cur:
        cur.execute(sql)
