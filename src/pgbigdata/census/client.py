"""Census ACS API client.

Responsibilities (the "consuming REST APIs at scale" part of the JD):
  * auth via optional API key
  * client-side rate limiting (token-bucket-lite: a min interval between calls)
  * retries with exponential backoff + jitter on 429 / 5xx / network errors
  * chunking large pulls by parent geography (the API has no cursor pagination)
  * turning the Census 2-D array response into list[dict]
"""
from __future__ import annotations

import logging
import random
import time
from typing import Iterator

import requests

from ..config import Config
from .geography import GEOGRAPHIES, Geography

log = logging.getLogger(__name__)

# Status codes worth retrying. 429 = rate limited; 5xx = transient server side.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class CensusAPIError(RuntimeError):
    """Retryable failure (rate limit / transient server / network)."""


class CensusConfigError(RuntimeError):
    """Non-retryable: bad request, missing key, unknown variable/geography."""


class CensusClient:
    def __init__(self, cfg: Config, session: requests.Session | None = None):
        self.cfg = cfg
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "pgbigdata-acs/1.0"})
        self._last_request_ts = 0.0

    # --- low level -----------------------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_ts
        wait = self.cfg.min_request_interval_s - elapsed
        if wait > 0:
            time.sleep(wait)

    def _get(self, url: str, params: dict[str, str]) -> list[list[str]]:
        if self.cfg.census_api_key:
            params = {**params, "key": self.cfg.census_api_key}

        last_exc: Exception | None = None
        for attempt in range(self.cfg.max_retries + 1):
            self._throttle()
            try:
                resp = self.session.get(
                    url, params=params, timeout=self.cfg.request_timeout_s
                )
                self._last_request_ts = time.monotonic()

                # 204 with empty body = valid "no rows for this geo" answer.
                if resp.status_code == 204 or not resp.text.strip():
                    return []

                if resp.status_code in RETRYABLE_STATUS:
                    raise CensusAPIError(f"retryable status {resp.status_code}")
                if resp.status_code != 200:
                    # 4xx (bad variable/geo) is a bug, not a blip — fail fast.
                    raise CensusConfigError(
                        f"HTTP {resp.status_code} for {resp.url}: {resp.text[:200]}"
                    )

                # The Census API answers a keyless/invalid request with HTTP 200
                # and an HTML error page (e.g. "Missing Key"). Detect that and
                # fail fast with an actionable message — retrying won't help.
                ctype = resp.headers.get("Content-Type", "")
                if "json" not in ctype and resp.text.lstrip().startswith("<"):
                    hint = resp.text[:200].replace("\n", " ").strip()
                    raise CensusConfigError(
                        "Census API returned a non-JSON page (status 200). This is "
                        "usually a missing/invalid API key — set CENSUS_API_KEY. "
                        f"Body starts: {hint}"
                    )
                return resp.json()
            except CensusConfigError:
                raise  # non-retryable — propagate immediately
            except (requests.RequestException, CensusAPIError, ValueError) as exc:
                last_exc = exc
                if attempt >= self.cfg.max_retries:
                    break
                sleep_s = self.cfg.backoff_base_s * (2 ** attempt)
                sleep_s += random.uniform(0, sleep_s * 0.25)  # jitter
                log.warning(
                    "request failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt + 1, self.cfg.max_retries, exc, sleep_s,
                )
                time.sleep(sleep_s)

        raise CensusAPIError(f"giving up after retries: {last_exc}") from last_exc

    @staticmethod
    def _rows_to_dicts(matrix: list[list[str]]) -> list[dict[str, str]]:
        """First row is the header; the rest are records."""
        if not matrix:
            return []
        header, *rows = matrix
        return [dict(zip(header, row)) for row in rows]

    # --- high level ----------------------------------------------------------

    def list_state_fips(self, year: int, dataset: str) -> list[str]:
        """Fetch state FIPS codes used to fan out fine-grained geographies."""
        url = f"{self.cfg.census_base_url}/{year}/{dataset}"
        rows = self._rows_to_dicts(
            self._get(url, {"get": "NAME", "for": "state:*"})
        )
        return sorted(r["state"] for r in rows)

    def fetch(
        self, year: int, dataset: str, get: str, geography: str
    ) -> Iterator[dict[str, str]]:
        """Yield one dict per geography row, chunking by parent when required.

        This is where "pagination/rate limits at scale" actually happens: a
        national tract pull becomes ~50 throttled, retried, per-state requests
        streamed back as a single iterator the loader can consume lazily.
        """
        if geography not in GEOGRAPHIES:
            raise ValueError(f"unknown geography {geography!r}")
        geo = GEOGRAPHIES[geography]
        url = f"{self.cfg.census_base_url}/{year}/{dataset}"

        if geo.chunk_by:
            parents = self.list_state_fips(year, dataset)
            log.info("chunking %s by %s: %d requests", geography, geo.chunk_by, len(parents))
            for i, parent in enumerate(parents, 1):
                params = self._params(geo, get, parent_fips=parent)
                rows = self._rows_to_dicts(self._get(url, params))
                log.info("  [%d/%d] %s=%s -> %d rows", i, len(parents), geo.chunk_by, parent, len(rows))
                yield from rows
        else:
            params = self._params(geo, get)
            yield from self._rows_to_dicts(self._get(url, params))

    @staticmethod
    def _params(geo: Geography, get: str, parent_fips: str | None = None) -> dict[str, str]:
        params = {"get": get, "for": f"{geo.for_clause}:*"}
        if geo.in_clause:
            # Fan-out level (e.g. tract) pins its chunk parent; others use *.
            in_parts = []
            for parent in geo.in_clause:
                if parent == geo.chunk_by and parent_fips is not None:
                    in_parts.append(f"{parent}:{parent_fips}")
                else:
                    in_parts.append(f"{parent}:*")
            params["in"] = " ".join(in_parts)
        return params
