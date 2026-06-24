"""Environment-driven configuration.

Everything an operator needs to tune lives here so the pipeline behaves
identically on a laptop and on Cloud Run, configured purely through env vars.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str | None = None) -> str | None:
    val = os.environ.get(name, default)
    return val.strip() if isinstance(val, str) else val


@dataclass(frozen=True)
class Config:
    # --- Postgres ---
    database_url: str

    # --- Census API ---
    census_base_url: str = "https://api.census.gov/data"
    census_api_key: str | None = None  # required by the Census API (free signup)

    # --- HTTP behaviour ---
    request_timeout_s: float = 30.0
    max_retries: int = 5
    backoff_base_s: float = 1.0          # exponential: base * 2**attempt (+ jitter)
    min_request_interval_s: float = 0.2  # client-side rate limit (~5 req/s)

    @classmethod
    def from_env(cls) -> "Config":
        database_url = _env(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/pgbigdata",
        )
        return cls(
            database_url=database_url,  # type: ignore[arg-type]
            census_base_url=_env("CENSUS_BASE_URL", cls.census_base_url),  # type: ignore[arg-type]
            census_api_key=_env("CENSUS_API_KEY"),
            request_timeout_s=float(_env("REQUEST_TIMEOUT_S", "30") or 30),
            max_retries=int(_env("MAX_RETRIES", "5") or 5),
            backoff_base_s=float(_env("BACKOFF_BASE_S", "1.0") or 1.0),
            min_request_interval_s=float(_env("MIN_REQUEST_INTERVAL_S", "0.2") or 0.2),
        )
