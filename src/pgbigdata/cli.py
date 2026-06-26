"""Command-line entrypoint.

    python -m pgbigdata.cli init-db
    python -m pgbigdata.cli ingest-acs --year 2022 --geography county
    python -m pgbigdata.cli ingest-acs --year 2022 --geography tract --force
    python -m pgbigdata.cli status
"""
from __future__ import annotations

import argparse
import logging
import sys

from .config import Config
from .db import connect, run_sql_file
from .census import client as census_client
from .census.geography import GEOGRAPHIES
from .census.loader import already_loaded, load
from .census.transform import transform_row
from .census.variables import get_param
from .pums import loader as pums_loader
from .pums import variables as pums_vars
from .pums.client import fetch_pums
from .pums.transform import transform_row as transform_pums_row

SQL_FILES = ["sql/001_schema.sql", "sql/002_views.sql", "sql/003_pums.sql"]
DEFAULT_DATASET = "acs/acs5"
DEFAULT_PUMS_DATASET = "acs/acs1/pums"
DEFAULT_PUMS_STATES = ["56", "50", "11"]  # WY, VT, DC — small, fast demo


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_init_db(cfg: Config, _args: argparse.Namespace) -> int:
    with connect(cfg.database_url) as conn:
        for path in SQL_FILES:
            run_sql_file(conn, path)
    print("schema applied")
    return 0


def cmd_ingest_acs(cfg: Config, args: argparse.Namespace) -> int:
    geo = GEOGRAPHIES[args.geography]
    dataset = args.dataset

    with connect(cfg.database_url) as conn:
        if not args.force and already_loaded(conn, dataset, args.year, args.geography):
            print(
                f"{dataset} {args.year} {args.geography} already loaded "
                f"(use --force to re-run); skipping."
            )
            return 0

        client = census_client.CensusClient(cfg)
        raw_rows = client.fetch(args.year, dataset, get_param(), args.geography)
        records = (
            transform_row(row, dataset=dataset, year=args.year, geo=geo)
            for row in raw_rows
        )
        total = load(
            conn, records,
            dataset=dataset, year=args.year, geography=args.geography,
        )
    print(f"loaded {total} {args.geography} rows for {dataset} {args.year}")
    return 0


def cmd_ingest_pums(cfg: Config, args: argparse.Namespace) -> int:
    dataset = args.dataset
    states = [s.strip() for s in args.states.split(",")] if args.states else (
        pums_vars.ALL_STATE_FIPS if args.all_states else DEFAULT_PUMS_STATES
    )
    label = "pums"

    with connect(cfg.database_url) as conn:
        if not args.force and already_loaded(conn, dataset, args.year, label):
            print(
                f"{dataset} {args.year} pums already loaded "
                f"(use --force to re-run); skipping."
            )
            return 0

        client = census_client.CensusClient(cfg)
        raw_rows = fetch_pums(
            client, year=args.year, dataset=dataset,
            get=pums_vars.get_param(), states=states,
        )
        records = (
            transform_pums_row(row, dataset=dataset, year=args.year)
            for row in raw_rows
        )
        total = pums_loader.load(
            conn, records, dataset=dataset, year=args.year, geography=label,
        )
    print(f"loaded {total} PUMS person rows for {dataset} {args.year} ({len(states)} states)")
    return 0


def cmd_status(cfg: Config, _args: argparse.Namespace) -> int:
    with connect(cfg.database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT dataset, year, geography, status, row_count, finished_at "
            "FROM load_runs ORDER BY started_at DESC LIMIT 20"
        )
        rows = cur.fetchall()
    if not rows:
        print("no load runs yet")
        return 0
    for r in rows:
        print(
            f"{r['finished_at'] or '(running)':<28} "
            f"{r['dataset']:<10} {r['year']} {r['geography']:<8} "
            f"{r['status']:<8} {r['row_count'] or 0:>8} rows"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pgbigdata", description=__doc__)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="apply schema + views")

    ing = sub.add_parser("ingest-acs", help="ingest an ACS dataset/year/geography")
    ing.add_argument("--year", type=int, required=True)
    ing.add_argument("--geography", choices=sorted(GEOGRAPHIES), default="county")
    ing.add_argument("--dataset", default=DEFAULT_DATASET, help="e.g. acs/acs5")
    ing.add_argument("--force", action="store_true", help="re-load even if present")

    pums = sub.add_parser("ingest-pums", help="ingest ACS PUMS person microdata")
    pums.add_argument("--year", type=int, required=True)
    pums.add_argument("--dataset", default=DEFAULT_PUMS_DATASET, help="e.g. acs/acs1/pums")
    pums.add_argument("--states", help="comma-separated state FIPS (e.g. 06,48,36)")
    pums.add_argument("--all-states", action="store_true", help="all 50 states + DC")
    pums.add_argument("--force", action="store_true", help="re-load even if present")

    sub.add_parser("status", help="show recent load runs")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(getattr(args, "verbose", False))
    cfg = Config.from_env()

    handlers = {
        "init-db": cmd_init_db,
        "ingest-acs": cmd_ingest_acs,
        "ingest-pums": cmd_ingest_pums,
        "status": cmd_status,
    }
    return handlers[args.command](cfg, args)


if __name__ == "__main__":
    sys.exit(main())
