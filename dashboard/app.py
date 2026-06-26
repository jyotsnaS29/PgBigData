"""Slice-and-dice dashboard for the ingested ACS data.

A lightweight Streamlit UI over the same Postgres the pipeline loads. Filters in
the sidebar, multiple views in tabs. Run via `make dashboard`.
"""
from __future__ import annotations

import os

import pandas as pd
import psycopg
import streamlit as st

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/pgbigdata"
)

# Promoted typed columns + two fields pulled straight from the JSONB payload,
# to show both halves of the storage model in one view.
LOAD_SQL = """
SELECT geography, geoid, year, name,
       total_population,
       median_household_income,
       median_home_value,
       median_gross_rent,
       unemployed_count,
       bachelors_count,
       (raw->>'B25001_001E')::bigint AS housing_units,
       (raw->>'B11001_001E')::bigint AS households
FROM acs_observations
WHERE geography = %s
"""

METRICS = [
    "median_household_income",
    "median_home_value",
    "median_gross_rent",
    "total_population",
    "unemployed_count",
    "bachelors_count",
    "housing_units",
    "households",
]

st.set_page_config(page_title="ACS Explorer", layout="wide")


@st.cache_data(ttl=300, show_spinner="Loading from Postgres…")
def load(geography: str) -> pd.DataFrame:
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(LOAD_SQL, (geography,))
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=cols)
    # Numeric columns arrive as Python ints/None; ensure float dtype for charts.
    for col in METRICS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    # Derive a 'state' column from the Census NAME (last comma-separated part).
    df["state"] = df["name"].str.split(",").str[-1].str.strip()
    return df


@st.cache_data(ttl=300)
def geographies() -> list[str]:
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT geography FROM acs_observations ORDER BY 1")
        return [r[0] for r in cur.fetchall()]


# --- sidebar filters --------------------------------------------------------
st.sidebar.title("🔎 Filters")
try:
    geos = geographies()
except Exception as exc:  # noqa: BLE001
    st.error(
        f"Could not connect to Postgres at `{DATABASE_URL}`.\n\n{exc}\n\n"
        "Is the container up on port 5433? `docker ps --filter name=pgbigdata-db`"
    )
    st.stop()

geography = st.sidebar.selectbox("Geography", geos, index=geos.index("county") if "county" in geos else 0)
df = load(geography)

all_states = sorted(df["state"].dropna().unique())
states = st.sidebar.multiselect("State", all_states, default=[])
metric = st.sidebar.selectbox("Metric (for ranking & charts)", METRICS, index=0)

pop_max = int(df["total_population"].fillna(0).max())
min_pop = st.sidebar.slider("Min population", 0, pop_max, 0, step=max(1, pop_max // 100))
name_q = st.sidebar.text_input("Name contains")
top_n = st.sidebar.slider("Top N (rankings/charts)", 5, 50, 20, step=5)

# --- apply filters ----------------------------------------------------------
f = df.copy()
if states:
    f = f[f["state"].isin(states)]
if min_pop:
    f = f[f["total_population"].fillna(0) >= min_pop]
if name_q:
    f = f[f["name"].str.contains(name_q, case=False, na=False)]

# --- header / KPIs ----------------------------------------------------------
st.title("U.S. Census ACS Explorer")
st.caption(f"Source: `acs_observations` · geography **{geography}** · {len(f):,} of {len(df):,} rows after filters")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Rows", f"{len(f):,}")
c2.metric(f"Median {metric}", f"{f[metric].median():,.0f}" if f[metric].notna().any() else "—")
c3.metric("Total population", f"{int(f['total_population'].fillna(0).sum()):,}")
c4.metric("States in view", f["state"].nunique())

tab_table, tab_rank, tab_dist, tab_compare, tab_pivot = st.tabs(
    ["📋 Table", "🏆 Rankings", "📊 Distribution", "🔬 Compare", "🧮 By state"]
)

with tab_table:
    st.caption("Sortable — click a column header. Use the ⬇ on hover to export CSV.")
    st.dataframe(
        f.sort_values(metric, ascending=False, na_position="last"),
        width="stretch",
        hide_index=True,
        height=520,
    )

with tab_rank:
    st.subheader(f"Top {top_n} by {metric}")
    ranked = (
        f.dropna(subset=[metric])
        .sort_values(metric, ascending=False)
        .head(top_n)[["name", metric]]
        .set_index("name")
    )
    st.bar_chart(ranked, horizontal=True, height=max(300, top_n * 22))

with tab_dist:
    st.subheader(f"Distribution of {metric}")
    vals = f[[metric]].dropna()
    if vals.empty:
        st.info("No data for this metric under the current filters.")
    else:
        # Bucketed histogram via value_counts over cut bins.
        binned = pd.cut(vals[metric], bins=30)
        hist = binned.value_counts().sort_index()
        hist.index = [f"{int(i.left):,}" for i in hist.index]
        st.bar_chart(hist, height=380)
        st.caption(
            f"min {vals[metric].min():,.0f} · "
            f"median {vals[metric].median():,.0f} · "
            f"mean {vals[metric].mean():,.0f} · "
            f"max {vals[metric].max():,.0f}"
        )

with tab_compare:
    st.subheader("Income vs. home value")
    st.caption("Each point is one geography; spot the price-to-income spread.")
    sc = f[["median_household_income", "median_home_value", "total_population", "name", "state"]].dropna(
        subset=["median_household_income", "median_home_value"]
    )
    if sc.empty:
        st.info("Not enough data under current filters.")
    else:
        st.scatter_chart(
            sc,
            x="median_household_income",
            y="median_home_value",
            size="total_population",
            color="state" if 0 < sc["state"].nunique() <= 12 else None,
            height=520,
        )

with tab_pivot:
    st.subheader("Aggregated by state")
    agg = st.radio("Aggregation", ["median", "mean", "sum"], horizontal=True)
    pivot = (
        f.groupby("state")
        .agg(
            rows=("geoid", "count"),
            population=("total_population", "sum"),
            value=(metric, agg),
        )
        .sort_values("value", ascending=False)
    )
    pivot = pivot.rename(columns={"value": f"{agg}_{metric}"})
    st.dataframe(pivot, width="stretch", height=360)
    st.bar_chart(pivot[[f"{agg}_{metric}"]], height=360)
