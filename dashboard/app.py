"""Slice-and-dice dashboard for the ingested Census data.

Two datasets, switchable in the sidebar:
  * ACS aggregate  — county/tract typed columns + JSONB-derived fields.
  * PUMS microdata — person-level records; weighted aggregations are pushed
    down to Postgres (so it scales past what a browser could hold).

Run via `make dashboard`.
"""
from __future__ import annotations

import os

import pandas as pd
import psycopg
import streamlit as st

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/pgbigdata"
)

st.set_page_config(page_title="Census Explorer", layout="wide")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def run_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols)


@st.cache_data(ttl=300)
def table_exists(name: str) -> bool:
    df = run_df("SELECT to_regclass(%s) AS t", (name,))
    return df.iloc[0]["t"] is not None


# ===========================================================================
# ACS aggregate view
# ===========================================================================
ACS_LOAD_SQL = """
SELECT geography, geoid, year, name,
       total_population, median_household_income, median_home_value,
       median_gross_rent, unemployed_count, bachelors_count,
       (raw->>'B25001_001E')::bigint AS housing_units,
       (raw->>'B11001_001E')::bigint AS households
FROM acs_observations WHERE geography = %s
"""
ACS_METRICS = [
    "median_household_income", "median_home_value", "median_gross_rent",
    "total_population", "unemployed_count", "bachelors_count",
    "housing_units", "households",
]


@st.cache_data(ttl=300, show_spinner="Loading ACS from Postgres…")
def acs_load(geography: str) -> pd.DataFrame:
    df = run_df(ACS_LOAD_SQL, (geography,))
    for col in ACS_METRICS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["state"] = df["name"].str.split(",").str[-1].str.strip()
    return df


@st.cache_data(ttl=300)
def acs_geographies() -> list[str]:
    return run_df("SELECT DISTINCT geography FROM acs_observations ORDER BY 1")["geography"].tolist()


def render_acs() -> None:
    geos = acs_geographies()
    geography = st.sidebar.selectbox("Geography", geos, index=geos.index("county") if "county" in geos else 0)
    df = acs_load(geography)

    all_states = sorted(df["state"].dropna().unique())
    states = st.sidebar.multiselect("State", all_states, default=[])
    metric = st.sidebar.selectbox("Metric (ranking & charts)", ACS_METRICS, index=0)
    pop_max = int(df["total_population"].fillna(0).max())
    min_pop = st.sidebar.slider("Min population", 0, pop_max, 0, step=max(1, pop_max // 100))
    name_q = st.sidebar.text_input("Name contains")
    top_n = st.sidebar.slider("Top N", 5, 50, 20, step=5)

    f = df.copy()
    if states:
        f = f[f["state"].isin(states)]
    if min_pop:
        f = f[f["total_population"].fillna(0) >= min_pop]
    if name_q:
        f = f[f["name"].str.contains(name_q, case=False, na=False)]

    st.title("ACS aggregate explorer")
    st.caption(f"`acs_observations` · {geography} · {len(f):,} of {len(df):,} rows after filters")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rows", f"{len(f):,}")
    c2.metric(f"Median {metric}", f"{f[metric].median():,.0f}" if f[metric].notna().any() else "—")
    c3.metric("Total population", f"{int(f['total_population'].fillna(0).sum()):,}")
    c4.metric("States in view", f["state"].nunique())

    t_table, t_rank, t_dist, t_cmp, t_pivot = st.tabs(
        ["📋 Table", "🏆 Rankings", "📊 Distribution", "🔬 Compare", "🧮 By state"]
    )
    with t_table:
        st.dataframe(f.sort_values(metric, ascending=False, na_position="last"),
                     width="stretch", hide_index=True, height=520)
    with t_rank:
        ranked = (f.dropna(subset=[metric]).sort_values(metric, ascending=False)
                  .head(top_n)[["name", metric]].set_index("name"))
        st.bar_chart(ranked, horizontal=True, height=max(300, top_n * 22))
    with t_dist:
        vals = f[[metric]].dropna()
        if vals.empty:
            st.info("No data for this metric under current filters.")
        else:
            hist = pd.cut(vals[metric], bins=30).value_counts().sort_index()
            hist.index = [f"{int(i.left):,}" for i in hist.index]
            st.bar_chart(hist, height=380)
    with t_cmp:
        sc = f[["median_household_income", "median_home_value", "total_population", "name", "state"]].dropna(
            subset=["median_household_income", "median_home_value"])
        if sc.empty:
            st.info("Not enough data under current filters.")
        else:
            st.scatter_chart(sc, x="median_household_income", y="median_home_value",
                             size="total_population",
                             color="state" if 0 < sc["state"].nunique() <= 12 else None, height=520)
    with t_pivot:
        agg = st.radio("Aggregation", ["median", "mean", "sum"], horizontal=True)
        pivot = (f.groupby("state").agg(rows=("geoid", "count"),
                 population=("total_population", "sum"), value=(metric, agg))
                 .sort_values("value", ascending=False).rename(columns={"value": f"{agg}_{metric}"}))
        st.dataframe(pivot, width="stretch", height=360)
        st.bar_chart(pivot[[f"{agg}_{metric}"]], height=360)


# ===========================================================================
# PUMS microdata view  (weighted aggregations done in SQL)
# ===========================================================================
# Readable labels for a few coded fields (SQL CASE expressions).
SCHL_BUCKET = """CASE
  WHEN nullif(schl,'')::int BETWEEN 1 AND 15 THEN '1 No HS diploma'
  WHEN nullif(schl,'')::int IN (16,17)        THEN '2 HS grad / GED'
  WHEN nullif(schl,'')::int BETWEEN 18 AND 20 THEN '3 Some college / Assoc'
  WHEN nullif(schl,'')::int = 21              THEN '4 Bachelor''s'
  WHEN nullif(schl,'')::int = 22              THEN '5 Master''s'
  WHEN nullif(schl,'')::int = 23              THEN '6 Professional'
  WHEN nullif(schl,'')::int = 24              THEN '7 Doctorate'
  ELSE '0 Unknown' END"""
ESR_LABEL = """CASE
  WHEN esr IN ('1','2') THEN 'Employed'
  WHEN esr = '3'        THEN 'Unemployed'
  WHEN esr IN ('4','5') THEN 'Armed forces'
  WHEN esr = '6'        THEN 'Not in labor force'
  ELSE 'Under 16 / N/A' END"""
AGE_BUCKET = """CASE
  WHEN agep < 18 THEN '00-17'  WHEN agep < 25 THEN '18-24'
  WHEN agep < 35 THEN '25-34'  WHEN agep < 45 THEN '35-44'
  WHEN agep < 55 THEN '45-54'  WHEN agep < 65 THEN '55-64'
  ELSE '65+' END"""


@st.cache_data(ttl=300)
def pums_states() -> list[str]:
    return run_df("SELECT DISTINCT st FROM pums_person ORDER BY st")["st"].tolist()


def _where(states: list[str]) -> tuple[str, tuple]:
    if states:
        return " WHERE st = ANY(%s)", (states,)
    return "", ()


def render_pums() -> None:
    if not table_exists("pums_person"):
        st.title("PUMS microdata")
        st.info("No `pums_person` table yet. Load some: "
                "`python -m pgbigdata.cli ingest-pums --year 2022`")
        return

    avail = pums_states()
    states = st.sidebar.multiselect("State (FIPS)", avail, default=[])
    w, p = _where(states)

    st.title("PUMS microdata explorer")
    st.caption("`pums_person` · person-level records · all figures **weighted by PWGTP** unless noted")

    kpi = run_df(f"""
      SELECT count(*) AS sample,
             sum(pwgtp) AS wpop,
             round(sum(pincp::numeric*pwgtp) FILTER (WHERE pincp IS NOT NULL)
                   / NULLIF(sum(pwgtp) FILTER (WHERE pincp IS NOT NULL),0),0) AS wmean_income
      FROM pums_person{w}""", p).iloc[0]
    c1, c2, c3 = st.columns(3)
    c1.metric("Sample persons", f"{int(kpi['sample']):,}")
    c2.metric("Weighted population", f"{int(kpi['wpop'] or 0):,}")
    c3.metric("Weighted mean income", f"${int(kpi['wmean_income'] or 0):,}")

    t_inc, t_demo, t_edu, t_puma, t_tbl = st.tabs(
        ["💰 Income by PUMA", "👥 Age (weighted)", "🎓 Education × employment", "🧮 By PUMA", "📋 Sample rows"]
    )

    with t_inc:
        df = run_df(f"""
          SELECT st||'-'||puma AS puma, sum(pwgtp) AS weighted_population,
                 round(sum(pincp::numeric*pwgtp) FILTER (WHERE pincp IS NOT NULL)
                       / NULLIF(sum(pwgtp) FILTER (WHERE pincp IS NOT NULL),0),0) AS weighted_mean_income
          FROM pums_person{w} GROUP BY st, puma
          ORDER BY weighted_mean_income DESC NULLS LAST LIMIT 25""", p)
        st.caption("Weighted mean person income by PUMA (top 25)")
        st.bar_chart(df.set_index("puma")[["weighted_mean_income"]], horizontal=True, height=560)

    with t_demo:
        df = run_df(f"""
          SELECT {AGE_BUCKET} AS age_band, sum(pwgtp) AS weighted_population
          FROM pums_person{w} GROUP BY age_band ORDER BY age_band""", p)
        st.caption("Weighted population by age band")
        st.bar_chart(df.set_index("age_band"), height=400)

    with t_edu:
        df = run_df(f"""
          SELECT {SCHL_BUCKET} AS education, {ESR_LABEL} AS employment, sum(pwgtp) AS weighted_population
          FROM pums_person{w} GROUP BY education, employment ORDER BY education""", p)
        pivot = df.pivot_table(index="education", columns="employment",
                               values="weighted_population", aggfunc="sum", fill_value=0).sort_index()
        st.caption("Weighted population: educational attainment × employment status")
        st.bar_chart(pivot, height=440, stack=True)
        st.dataframe(pivot, width="stretch")

    with t_puma:
        df = run_df(f"""
          SELECT st, puma, count(*) AS sample_persons, sum(pwgtp) AS weighted_population,
                 round(sum(pincp::numeric*pwgtp) FILTER (WHERE pincp IS NOT NULL)
                       / NULLIF(sum(pwgtp) FILTER (WHERE pincp IS NOT NULL),0),0) AS weighted_mean_income
          FROM pums_person{w} GROUP BY st, puma ORDER BY weighted_population DESC""", p)
        st.dataframe(df, width="stretch", hide_index=True, height=440)

    with t_tbl:
        df = run_df(f"""
          SELECT serialno, sporder, st, puma, pwgtp, agep, sex, schl, esr, pincp, wagp
          FROM pums_person{w} ORDER BY pwgtp DESC LIMIT 500""", p)
        st.caption("Sample of individual person records (top 500 by weight)")
        st.dataframe(df, width="stretch", hide_index=True, height=440)


# ===========================================================================
# Router
# ===========================================================================
st.sidebar.title("🔎 Census Explorer")
try:
    dataset = st.sidebar.radio("Dataset", ["ACS aggregate", "PUMS microdata"])
    st.sidebar.divider()
    if dataset == "ACS aggregate":
        render_acs()
    else:
        render_pums()
except Exception as exc:  # noqa: BLE001
    st.error(
        f"Could not query Postgres at `{DATABASE_URL}`.\n\n{exc}\n\n"
        "Is the DB up? `docker ps --filter name=pgbigdata-db`"
    )
    st.stop()
