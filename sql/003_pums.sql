-- ============================================================================
-- PUMS person-level microdata.
--
-- One row = one weighted person. Same storage model as the aggregate tables:
-- promoted typed columns for what we filter/group/weight on, plus the complete
-- record in JSONB. Natural key is (serialno, sporder), not a GEOID.
-- ============================================================================

CREATE TABLE IF NOT EXISTS pums_person (
    dataset    text    NOT NULL,
    year       int     NOT NULL,
    serialno   text    NOT NULL,     -- housing-unit serial (e.g. '2022GQ0000581')
    sporder    integer NOT NULL,     -- person # within the household

    st         text,                 -- state FIPS (from for=state:NN)
    puma       text,                 -- Public Use Microdata Area

    pwgtp      integer,              -- person weight (expansion factor) — weight every estimate
    agep       integer,
    sex        text,
    rac1p      text,
    hisp       text,
    schl       text,
    esr        text,
    cow        text,
    wkhp       integer,
    jwmnp      integer,
    occp       text,
    indp       text,
    pincp      integer,              -- person income (may be negative)
    wagp       integer,
    hicov      text,

    raw        jsonb   NOT NULL,

    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (dataset, year, serialno, sporder)
);

-- Filter/group by geography (state, PUMA) and vintage.
CREATE INDEX IF NOT EXISTS idx_pums_geo   ON pums_person (year, st, puma);
-- Income analysis (skip the many NULLs).
CREATE INDEX IF NOT EXISTS idx_pums_pincp ON pums_person (pincp) WHERE pincp IS NOT NULL;
-- Containment queries against un-promoted PUMS fields.
CREATE INDEX IF NOT EXISTS idx_pums_raw_gin ON pums_person USING gin (raw jsonb_path_ops);

-- Weighted summary helper: e.g. weighted population & mean income by state/PUMA.
CREATE OR REPLACE VIEW v_pums_income_by_puma AS
SELECT
    year, st, puma,
    count(*)                                            AS sample_persons,
    sum(pwgtp)                                          AS weighted_population,
    round(sum(pincp::numeric * pwgtp)
          / NULLIF(sum(pwgtp) FILTER (WHERE pincp IS NOT NULL), 0), 0)
                                                        AS weighted_mean_income
FROM pums_person
GROUP BY year, st, puma;
