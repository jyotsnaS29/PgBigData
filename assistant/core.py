"""NL → SQL core for the data assistant (standalone — no Streamlit).

Mirrors the safety model used elsewhere:
  1. The model is told to emit one read-only SELECT.
  2. is_safe() rejects anything that isn't a single SELECT/WITH.
  3. run_readonly() runs inside a READ ONLY transaction with a statement
     timeout and a row cap, then rolls back.
The answer is grounded: summaries use only the returned rows.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
from decimal import Decimal

import psycopg
from openai import OpenAI

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|"
    r"copy|vacuum|comment|merge|call|do|set|reset)\b",
    re.IGNORECASE,
)

RELATIONS = (
    "acs_observations", "pums_person", "cces_response",
    "v_acs_latest", "v_pums_income_by_puma", "v_cces_acs_county",
)

SYSTEM_PROMPT = """You are a PostgreSQL expert writing queries for a Census data warehouse.
Given a question, return ONE read-only SELECT query (PostgreSQL dialect) that answers it.

Which relation to use:
- acs_observations: aggregate county/tract facts (population, median income, home
  value, rent, etc.). Filter by geography ('county'|'tract') and year.
- pums_person: person-level microdata; weight estimates by PWGTP.
- cces_response: survey respondents; weight estimates by commonweight.
- v_cces_acs_county: ONLY when relating CCES respondents to their ACS county
  (sparse otherwise). Do not use it for plain county rankings.

Hard rules:
- Output ONLY the SQL. No prose, no markdown code fences.
- SELECT or WITH only. Never modify data. A single statement, no semicolons.
- Include a LIMIT (<= 200) for non-aggregated row listings.
- Weight survey/microdata estimates: pums_person by PWGTP, cces_response by commonweight.
- Years available: ACS & PUMS = 2022, 2023, 2024; CCES = 2022, 2024.
- When ranking by a metric with ORDER BY ... DESC, append NULLS LAST.
- round(double precision, n) does not exist — cast to numeric: round(x::numeric, n).
"""

SUMMARY_PROMPT = (
    "You are given the FULL result of a SQL query, as CSV (header + rows). "
    "Answer the user's question in 1-2 sentences using ONLY these rows.\n"
    "- Cite exact figures that appear in the data; round only for readability.\n"
    "- NEVER invent or estimate any value not in the rows.\n"
    "- If there are no data rows, reply exactly: No matching data.\n"
    "- Do not mention SQL, CSV, or columns."
)


def _conn() -> psycopg.Connection:
    return psycopg.connect(os.environ["DATABASE_URL"])


def model_name() -> str:
    return os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


def _client() -> OpenAI:
    return OpenAI()


def build_schema() -> str:
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT table_name, string_agg(column_name, ', ' ORDER BY ordinal_position) "
            "FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name = ANY(%s) GROUP BY table_name",
            (list(RELATIONS),),
        )
        by = {t: cols for t, cols in cur.fetchall()}
    lines = [f"{n} ({by[n]})" for n in RELATIONS if n in by]
    lines.append(
        "Notes: v_cces_acs_county exposes each respondent's county_median_income / "
        "county_population (no join needed); filter by year, weight by commonweight."
    )
    return "\n".join(lines)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def is_safe(sql: str) -> tuple[bool, str]:
    s = sql.strip().rstrip(";").strip()
    if not s:
        return False, "empty query"
    if ";" in s:
        return False, "multiple statements are not allowed"
    if not re.match(r"^(select|with)\b", s, re.IGNORECASE):
        return False, "only SELECT / WITH queries are allowed"
    if FORBIDDEN.search(s):
        return False, "query contains a write/DDL keyword"
    return True, ""


def generate_sql(question: str, schema: str) -> str:
    resp = _client().chat.completions.create(
        model=model_name(), temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT + "\n\nSCHEMA:\n" + schema},
            {"role": "user", "content": question},
        ],
    )
    return _strip_fences(resp.choices[0].message.content or "")


def _jsonable(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.isoformat()
    return v


def run_readonly(sql: str, max_rows: int = 200) -> tuple[list[str], list[list]]:
    conn = _conn()
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SET LOCAL statement_timeout = '15s'")
            cur.execute(sql)
            cols = [d.name for d in cur.description]
            rows = [[_jsonable(v) for v in r] for r in cur.fetchmany(max_rows)]
        return cols, rows
    finally:
        conn.rollback()
        conn.close()


def rows_to_csv(cols: list[str], rows: list[list], limit: int = 100) -> str:
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows[:limit]:
        w.writerow(r)
    return buf.getvalue()


def summarize_stream(question: str, rows_preview: str):
    stream = _client().chat.completions.create(
        model=model_name(), temperature=0, stream=True,
        messages=[
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": f"Question: {question}\n\nResult rows:\n{rows_preview}"},
        ],
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
