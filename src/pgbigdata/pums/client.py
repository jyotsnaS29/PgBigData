"""PUMS fetch: chunk by state.

PUMS geography only goes to state + PUMA, and a national pull is huge, so we
fan out one request per state (exactly the tract pattern) over the shared,
throttled, retried HTTP client.
"""
from __future__ import annotations

import logging
from typing import Iterator

from ..census.client import CensusClient

log = logging.getLogger(__name__)


def fetch_pums(
    client: CensusClient, *, year: int, dataset: str, get: str, states: list[str]
) -> Iterator[dict[str, str]]:
    log.info("PUMS pull: %d state requests for %s %s", len(states), dataset, year)
    for i, st in enumerate(states, 1):
        rows = client.get_rows(year, dataset, {"get": get, "for": f"state:{st}"})
        log.info("  [%d/%d] state=%s -> %d person rows", i, len(states), st, len(rows))
        yield from rows
