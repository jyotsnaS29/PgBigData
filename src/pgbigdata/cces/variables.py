"""CCES promotion map + per-year Dataverse file ids.

Promotion principle (same as the rest of the project): a column earns a typed,
indexed column only if we filter/join/weight on it. For CCES that's the survey
weights, the geography *crosswalk keys* (which link a respondent to ACS places),
and a handful of core demographics + political identifiers. The other ~500
`CC18_*` question items stay in JSONB until a specific analysis needs them.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CcesVar:
    col: str        # source column name (== destination column)
    pg_type: str    # Postgres type for DDL
    kind: str       # 'bigint' | 'int' | 'float' | 'text'
    label: str


KEY = CcesVar("caseid", "bigint", "bigint", "Respondent ID")

PROMOTED = [
    # Survey weights — every population estimate must be weighted.
    CcesVar("commonweight",     "double precision", "float", "Common content weight"),
    CcesVar("commonpostweight", "double precision", "float", "Post-election weight"),
    CcesVar("vvweight",         "double precision", "float", "Vote-validated weight"),
    # Geography crosswalk keys — link respondents to ACS geographies.
    CcesVar("inputstate", "text", "text", "State FIPS"),
    CcesVar("countyfips", "text", "text", "County FIPS (joins to ACS county geoid)"),
    CcesVar("cdid116",    "text", "text", "116th Congressional district"),
    # Core demographics.
    CcesVar("birthyr",  "integer", "int",  "Birth year"),
    CcesVar("gender",   "text",    "text", "Gender (1=male, 2=female)"),
    CcesVar("educ",     "text",    "text", "Education category"),
    CcesVar("race",     "text",    "text", "Race category"),
    CcesVar("hispanic", "text",    "text", "Hispanic flag"),
    CcesVar("marstat",  "text",    "text", "Marital status"),
    # Political identifiers.
    CcesVar("votereg", "text", "text", "Voter registration status"),
    CcesVar("pid3",    "text", "text", "Party ID (3-point)"),
    CcesVar("pid7",    "text", "text", "Party ID (7-point)"),
    CcesVar("ideo5",   "text", "text", "Ideology (5-point)"),
]

# Harvard Dataverse datafile ids for the ingested .tab (tab-separated) version,
# per survey year. Add more as needed, or pass --file-id on the CLI.
#   CCES Common Content 2018 -> doi:10.7910/DVN/ZSBZ7K
DATAVERSE_FILE_IDS = {
    2018: 3588803,
}


def coerce(kind: str, raw: str | None):
    if raw is None:
        return None
    raw = raw.strip()
    if raw == "":
        return None
    if kind == "text":
        return raw
    try:
        if kind in ("bigint", "int"):
            return int(float(raw))
        if kind == "float":
            return float(raw)
    except (TypeError, ValueError):
        return None
    return None
