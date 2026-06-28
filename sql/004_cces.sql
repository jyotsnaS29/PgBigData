-- ============================================================================
-- CCES (Cooperative Election Study) survey responses.
--
-- One row = one survey respondent. Promoted: weights, geography crosswalk keys,
-- core demographics, political IDs. The ~500 question items live in JSONB.
-- Natural key: (year, caseid).
-- ============================================================================

CREATE TABLE IF NOT EXISTS cces_response (
    dataset          text   NOT NULL,
    year             int    NOT NULL,
    caseid           bigint NOT NULL,

    -- survey weights
    commonweight     double precision,
    commonpostweight double precision,
    vvweight         double precision,

    -- geography crosswalk keys (link respondents to ACS places)
    inputstate       text,
    countyfips       text,
    cdid116          text,

    -- demographics
    birthyr          integer,
    gender           text,
    educ             text,
    race             text,
    hispanic         text,
    marstat          text,

    -- political identifiers
    votereg          text,
    pid3             text,
    pid7             text,
    ideo5            text,

    raw        jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (year, caseid)
);

CREATE INDEX IF NOT EXISTS idx_cces_state  ON cces_response (year, inputstate);
CREATE INDEX IF NOT EXISTS idx_cces_county ON cces_response (countyfips) WHERE countyfips IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cces_pid    ON cces_response (year, pid3);

-- ----------------------------------------------------------------------------
-- The crosswalk payoff: join each respondent to their county's ACS data.
-- CCES stores county FIPS without a leading zero (integer-derived), so we
-- lpad to the 5-digit ACS geoid before joining.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_cces_acs_county AS
SELECT
    c.year, c.caseid, c.commonweight,
    c.inputstate, c.countyfips, c.gender, c.educ, c.pid3, c.ideo5,
    a.name                    AS county_name,
    a.total_population        AS county_population,
    a.median_household_income AS county_median_income
FROM cces_response c
LEFT JOIN acs_observations a
       ON a.geography = 'county'
      AND a.geoid = lpad(c.countyfips, 5, '0');
