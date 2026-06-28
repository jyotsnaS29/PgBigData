"""Natural-language → SQL over the Census warehouse, via OpenAI.

Safety model (defence in depth):
  1. The model is instructed to emit a single read-only SELECT.
  2. is_safe() rejects anything that isn't one SELECT/WITH (no DDL/DML, no
     multiple statements).
  3. run_readonly() executes inside a READ ONLY transaction with a statement
     timeout and caps the rows fetched — so even a bad query can't write or hang.
"""
from __future__ import annotations

import os
import re

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|"
    r"copy|vacuum|comment|merge|call|do|set|reset)\b",
    re.IGNORECASE,
)

SYSTEM_PROMPT = """You are a PostgreSQL expert writing queries for a Census data warehouse.
Given a question, return ONE read-only SELECT query (PostgreSQL dialect) that answers it.

Which relation to use:
- acs_observations: aggregate county/tract facts (population, median income, home
  value, rent, etc.). Filter by geography ('county'|'tract') and year.
- pums_person: person-level microdata; weight estimates by PWGTP.
- cces_response: survey respondents; weight estimates by commonweight.
- v_cces_acs_county: ONLY when relating CCES respondents to their ACS county
  (it is sparse for non-CCES questions). Do not use it for plain county rankings.

Hard rules:
- Output ONLY the SQL. No prose, no markdown code fences.
- SELECT or WITH only. Never modify data. A single statement, no semicolons.
- Include a LIMIT (<= 200) for non-aggregated row listings.
- Weight survey/microdata estimates: pums_person by PWGTP, cces_response by commonweight.
- Years available: ACS & PUMS = 2022, 2023, 2024; CCES = 2022, 2024.
- When ranking by a metric with ORDER BY ... DESC, append NULLS LAST.
"""

SUMMARY_PROMPT = (
    "Answer the user's question in one or two sentences using ONLY the result "
    "rows provided. Be specific with numbers. Do not mention SQL."
)


RELATIONS = (
    "acs_observations", "pums_person", "cces_response",        # tables
    "v_acs_latest", "v_pums_income_by_puma", "v_cces_acs_county",  # views
)


def build_schema(run_df) -> str:
    """Introspect the live schema (tables AND views) so the prompt matches
    reality and the model never has to guess column names."""
    cols = run_df(
        """
        SELECT table_name,
               string_agg(column_name, ', ' ORDER BY ordinal_position) AS cols
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = ANY(%s)
        GROUP BY table_name
        """,
        (list(RELATIONS),),
    )
    by_name = {r.table_name: r.cols for r in cols.itertuples()}
    lines = [f"{name} ({by_name[name]})" for name in RELATIONS if name in by_name]
    lines.append(
        "Notes: v_cces_acs_county already exposes each respondent's "
        "county_median_income / county_population (no join needed); just filter "
        "by year and weight by commonweight."
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


def _client():
    from openai import OpenAI

    return OpenAI()  # reads OPENAI_API_KEY from the environment


def model_name() -> str:
    return os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


def generate_sql(question: str, schema: str) -> str:
    resp = _client().chat.completions.create(
        model=model_name(),
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT + "\n\nSCHEMA:\n" + schema},
            {"role": "user", "content": question},
        ],
    )
    return _strip_fences(resp.choices[0].message.content or "")


def summarize(question: str, rows_preview: str) -> str:
    resp = _client().chat.completions.create(
        model=model_name(),
        temperature=0,
        messages=[
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": f"Question: {question}\n\nResult rows:\n{rows_preview}"},
        ],
    )
    return (resp.choices[0].message.content or "").strip()
