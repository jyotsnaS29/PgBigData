"""ACS variable catalog and the *promotion map*.

This module encodes the single most important storage decision in the project
(see docs/DESIGN.md): which incoming fields get *promoted* to typed, indexed
columns versus which stay inside the raw JSONB payload.

A variable is promoted when we expect to **filter, sort, join, or expose it to
the CMS directly**. Everything else the API returns is preserved verbatim in
JSONB so we never lose data and can promote more fields later without a
re-ingest.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromotedVar:
    code: str          # ACS variable id, e.g. "B19013_001E"
    column: str        # destination typed column
    pg_type: str       # Postgres type for DDL generation
    label: str         # human description (also surfaced to Payload)


# Curated, high-value fields we query and expose downstream. Kept deliberately
# small: promotion is cheap to add later, expensive to over-do up front.
PROMOTED: list[PromotedVar] = [
    PromotedVar("B01001_001E", "total_population",        "bigint",  "Total population"),
    PromotedVar("B19013_001E", "median_household_income", "integer", "Median household income (USD)"),
    PromotedVar("B25077_001E", "median_home_value",       "integer", "Median value, owner-occupied homes (USD)"),
    PromotedVar("B25064_001E", "median_gross_rent",       "integer", "Median gross rent (USD)"),
    PromotedVar("B23025_005E", "unemployed_count",        "integer", "Unemployed population (16+, civilian)"),
    PromotedVar("B15003_022E", "bachelors_count",         "integer", "Population 25+ with a bachelor's degree"),
]

# Variables we always request alongside the promoted ones for context. NAME is
# the Census-provided human label for the geography.
ALWAYS_FETCH = ["NAME"]

# Fields we fetch and keep in the raw JSONB payload but deliberately do NOT
# promote to typed columns — we want the data on hand, but don't (yet) filter
# or join on it. Reachable via `raw ->> 'CODE'`; see v_acs_county_housing.
EXTRA_FETCH = [
    "B25001_001E",  # total housing units
    "B11001_001E",  # total households
]


def promoted_codes() -> list[str]:
    return [v.code for v in PROMOTED]


def get_param() -> str:
    """Comma-separated `get=` value for the API call.

    Census caps a single request at 50 variables; this curated set stays well
    under that. For wide pulls a real run would batch codes into <=50 chunks
    and merge on geoid — the chunking machinery already exists in client.py.
    """
    return ",".join(ALWAYS_FETCH + promoted_codes() + EXTRA_FETCH)


# ACS encodes special/missing values as large negative jam sentinels. Anything
# at or below this magnitude is treated as NULL for the typed columns.
JAM_SENTINEL_THRESHOLD = -666666666


def coerce_numeric(raw: str | None) -> int | None:
    """Census returns numbers as strings; sentinels mean 'no data'."""
    if raw is None or raw == "":
        return None
    try:
        val = int(float(raw))
    except (TypeError, ValueError):
        return None
    if val <= JAM_SENTINEL_THRESHOLD:
        return None
    return val
