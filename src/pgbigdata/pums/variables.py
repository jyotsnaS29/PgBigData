"""PUMS person-record variable catalog and promotion map.

PUMS (Public Use Microdata Sample) returns *individual* person records rather
than aggregated geographies — each row is one weighted person. The storage
decision is the same as the aggregate ACS pipeline: promote the analytically
key fields (weight, geography, income, demographics) to typed columns; keep the
complete row in JSONB.

Two PUMS-specific wrinkles vs. the aggregate tables:
  * The natural key is (SERIALNO, SPORDER) — housing-unit serial + person number
    within the household — not a GEOID.
  * Every estimate must be *weighted* by PWGTP. It is always promoted.

Note the Census 50-variable-per-request cap: this set stays under it. The 80
replicate weights (PWGTP1..PWGTP80), needed for variance estimation, would blow
the cap and are intentionally left for a separate, merged-on-key pull.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PumsVar:
    code: str       # PUMS variable id, e.g. "PINCP"
    column: str     # destination typed column
    pg_type: str    # Postgres type
    numeric: bool   # parse as int? (income can be negative — no jam sentinels)
    label: str


# Key fields (also promoted) — identify the record.
KEY = [
    PumsVar("SERIALNO", "serialno", "text",   False, "Housing-unit serial number"),
    PumsVar("SPORDER",  "sporder",  "integer", True, "Person number within household"),
]

# Geography: ST comes from the `for=state:NN` response column 'state', not a get
# var; PUMA is requested explicitly.
GEO = [
    PumsVar("PUMA", "puma", "text", False, "Public Use Microdata Area code"),
]

# Promoted analytic fields.
PROMOTED = [
    PumsVar("PWGTP", "pwgtp", "integer", True,  "Person weight (expansion factor)"),
    PumsVar("AGEP",  "agep",  "integer", True,  "Age"),
    PumsVar("SEX",   "sex",   "text",    False, "Sex (1=male, 2=female)"),
    PumsVar("RAC1P", "rac1p", "text",    False, "Recoded detailed race code"),
    PumsVar("HISP",  "hisp",  "text",    False, "Hispanic origin code"),
    PumsVar("SCHL",  "schl",  "text",    False, "Educational attainment code"),
    PumsVar("ESR",   "esr",   "text",    False, "Employment status recode"),
    PumsVar("COW",   "cow",   "text",    False, "Class of worker"),
    PumsVar("WKHP",  "wkhp",  "integer", True,  "Usual hours worked per week"),
    PumsVar("JWMNP", "jwmnp", "integer", True,  "Commute time (minutes)"),
    PumsVar("OCCP",  "occp",  "text",    False, "Occupation code"),
    PumsVar("INDP",  "indp",  "text",    False, "Industry code"),
    PumsVar("PINCP", "pincp", "integer", True,  "Total person income (USD, may be negative)"),
    PumsVar("WAGP",  "wagp",  "integer", True,  "Wages/salary income (USD)"),
    PumsVar("HICOV", "hicov", "text",    False, "Health insurance coverage recode"),
]

ALL_VARS = KEY + GEO + PROMOTED              # everything we request
DATA_COLUMNS = GEO + PROMOTED                # promoted, excluding the key cols


def get_param() -> str:
    """`get=` value — all requested PUMS variables (stays under the 50 cap)."""
    return ",".join(v.code for v in ALL_VARS)


def coerce_int(raw: str | None) -> int | None:
    """Parse a PUMS integer. Unlike the aggregate tables, negatives are valid
    (e.g. business-loss income), so we do NOT nullify them."""
    if raw is None or raw == "":
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def coerce_text(raw: str | None) -> str | None:
    """Keep categorical codes verbatim (leading zeros matter), '' -> NULL."""
    if raw is None or raw == "":
        return None
    return raw


# 50 states + DC (FIPS), used to fan out a national pull. PUMS geography only
# goes down to state + PUMA, so we chunk by state exactly like tracts.
ALL_STATE_FIPS = [
    "01", "02", "04", "05", "06", "08", "09", "10", "11", "12", "13", "15",
    "16", "17", "18", "19", "20", "21", "22", "23", "24", "25", "26", "27",
    "28", "29", "30", "31", "32", "33", "34", "35", "36", "37", "38", "39",
    "40", "41", "42", "44", "45", "46", "47", "48", "49", "50", "51", "53",
    "54", "55", "56",
]
