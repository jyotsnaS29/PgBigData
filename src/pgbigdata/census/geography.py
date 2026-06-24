"""Geography definitions for the ACS API.

The Census API has no offset/cursor pagination. Instead, large pulls are
*chunked by parent geography*: you cannot ask for every census tract in the
country in one call, so you fan out one request per state. This module declares,
per geography level, how to request it and how to build a stable GEOID natural
key from the returned geo columns.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Geography:
    name: str                      # our canonical level name
    for_clause: str                # value for the API `for=` param
    geoid_parts: list[str]         # geo columns, in order, that form the GEOID
    in_clause: list[str] = field(default_factory=list)  # required parent columns
    chunk_by: str | None = None    # parent level to fan out over for big pulls


GEOGRAPHIES: dict[str, Geography] = {
    "us": Geography(
        name="us", for_clause="us", geoid_parts=["us"],
    ),
    "state": Geography(
        name="state", for_clause="state", geoid_parts=["state"],
    ),
    "county": Geography(
        name="county", for_clause="county", geoid_parts=["state", "county"],
        in_clause=["state"],  # in=state:* returns all counties in one call
    ),
    "place": Geography(
        name="place", for_clause="place", geoid_parts=["state", "place"],
        in_clause=["state"], chunk_by="state",
    ),
    "tract": Geography(
        name="tract", for_clause="tract", geoid_parts=["state", "county", "tract"],
        in_clause=["state"], chunk_by="state",  # one request per state
    ),
    "zcta": Geography(
        name="zcta", for_clause="zip code tabulation area",
        geoid_parts=["zip code tabulation area"],
    ),
}


def build_geoid(geo: Geography, row: dict[str, str]) -> str:
    """Concatenate geo component codes into a stable GEOID.

    Mirrors the Census GEOID convention (e.g. state+county+tract). This is the
    natural key we upsert on, making loads idempotent across re-runs.
    """
    return "".join(row[part] for part in geo.geoid_parts)
