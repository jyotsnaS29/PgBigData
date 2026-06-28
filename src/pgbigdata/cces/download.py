"""Download + parse CCES bulk files from Harvard Dataverse.

Dataverse's access endpoint 303-redirects to S3; requests follows it. Downloads
are cached on disk so re-runs (and the idempotent loader) don't re-pull 100+ MB.
"""
from __future__ import annotations

import csv
import logging
import os
import tempfile
from typing import Iterator

import requests

log = logging.getLogger(__name__)

DATAVERSE_BASE = "https://dataverse.harvard.edu"
CHUNK = 1 << 20  # 1 MiB


def cache_path(year: int, file_id: int) -> str:
    cache_dir = os.environ.get("CCES_CACHE_DIR", tempfile.gettempdir())
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"cces_{year}_{file_id}.tab")


def download(file_id: int, dest: str, *, timeout: float = 120.0) -> str:
    """Download a Dataverse datafile to dest (cached, atomic). Returns dest."""
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        log.info("using cached file %s (%.1f MB)", dest, os.path.getsize(dest) / 1e6)
        return dest

    url = f"{DATAVERSE_BASE}/api/access/datafile/{file_id}"
    log.info("downloading %s", url)
    tmp = dest + ".part"
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        written = 0
        with open(tmp, "wb") as fh:
            for chunk in r.iter_content(CHUNK):
                fh.write(chunk)
                written += len(chunk)
        log.info("downloaded %.1f MB", written / 1e6)
    os.replace(tmp, dest)
    return dest


def iter_rows(path: str) -> Iterator[dict[str, str]]:
    """Yield each respondent as a dict. Auto-detects the delimiter — 2018 ships
    as .tab (tab-separated), 2022/2024 as .csv. utf-8-sig strips any BOM."""
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
        first = fh.readline()
        delimiter = "\t" if first.count("\t") > first.count(",") else ","
        fh.seek(0)
        yield from csv.DictReader(fh, delimiter=delimiter)
