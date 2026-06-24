-- ============================================================================
-- Views: the stable, CMS-facing contract.
--
-- Payload (or any consumer) reads these instead of the base table, so we can
-- refactor storage, promote new JSONB fields, or re-partition underneath
-- without breaking downstream content fields. See docs/PAYLOAD.md.
-- ============================================================================

-- Clean, typed projection for the latest vintage of each geography.
CREATE OR REPLACE VIEW v_acs_latest AS
SELECT DISTINCT ON (geography, geoid)
    geography,
    geoid,
    year,
    name,
    total_population,
    median_household_income,
    median_home_value,
    median_gross_rent,
    unemployed_count,
    bachelors_count,
    updated_at
FROM acs_observations
ORDER BY geography, geoid, year DESC;

-- Example of surfacing a NON-promoted field straight from JSONB on demand.
-- B25064_001E is already promoted; here we pull an un-promoted housing-units
-- estimate (B25001_001E) to show the pattern works without a migration.
CREATE OR REPLACE VIEW v_acs_county_housing AS
SELECT
    geoid,
    year,
    name,
    total_population,
    (raw ->> 'B25001_001E')::bigint AS housing_units_from_jsonb
FROM acs_observations
WHERE geography = 'county';
