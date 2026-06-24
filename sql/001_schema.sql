-- ============================================================================
-- pgbigdata schema
--
-- Storage model (see docs/DESIGN.md):
--   * Typed, indexed columns for the handful of fields we filter / sort / join
--     / expose to the CMS.
--   * A single JSONB `raw` column holding the *complete* API payload, so we
--     never lose data and can promote more fields later without re-ingesting.
-- ============================================================================

CREATE TABLE IF NOT EXISTS acs_observations (
    -- Natural key: a row is one geography's values for one dataset vintage.
    dataset                  text    NOT NULL,
    year                     int     NOT NULL,
    geography                text    NOT NULL,        -- 'county', 'tract', ...
    geoid                    text    NOT NULL,        -- e.g. '01001' (state+county)

    -- Promoted, queryable columns -------------------------------------------
    name                     text,                    -- Census human label
    total_population         bigint,
    median_household_income  integer,
    median_home_value        integer,
    median_gross_rent        integer,
    unemployed_count         integer,
    bachelors_count          integer,

    -- Everything the API returned, verbatim ---------------------------------
    raw                      jsonb   NOT NULL,

    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (dataset, year, geography, geoid)
);

-- Typed-column indexes: these back the filters/sorts the CMS and analysts run.
CREATE INDEX IF NOT EXISTS idx_acs_geography      ON acs_observations (geography, year);
CREATE INDEX IF NOT EXISTS idx_acs_med_income     ON acs_observations (median_household_income)
    WHERE median_household_income IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_acs_population     ON acs_observations (total_population)
    WHERE total_population IS NOT NULL;

-- GIN index on the JSONB payload: enables containment (@>) and key-exists (?)
-- queries against fields we have NOT promoted, without a schema migration.
-- jsonb_path_ops is smaller/faster when you only need @> containment.
CREATE INDEX IF NOT EXISTS idx_acs_raw_gin
    ON acs_observations USING gin (raw jsonb_path_ops);


-- ----------------------------------------------------------------------------
-- Load run audit log: powers incremental loads (skip already-loaded vintages)
-- and gives operators a record of what ran, when, and whether it succeeded.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS load_runs (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dataset     text NOT NULL,
    year        int  NOT NULL,
    geography   text NOT NULL,
    status      text NOT NULL DEFAULT 'running',  -- running | success | failed
    row_count   bigint,
    error       text,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_load_runs_lookup
    ON load_runs (dataset, year, geography, status);
