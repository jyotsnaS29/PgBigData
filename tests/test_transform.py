"""Unit tests for the pure transform layer — no DB or network required.

    pytest -q
"""
from pgbigdata.census.geography import GEOGRAPHIES, build_geoid
from pgbigdata.census.transform import record_as_db_params, transform_row
from pgbigdata.census.variables import coerce_numeric


def _county_row():
    return {
        "NAME": "Autauga County, Alabama",
        "B01001_001E": "58805",
        "B19013_001E": "67565",
        "B25077_001E": "174600",
        "B25064_001E": "1042",
        "B23025_005E": "1832",
        "B15003_022E": "6543",
        "B25001_001E": "24571",   # extra (JSONB-only)
        "B11001_001E": "21478",   # extra (JSONB-only)
        "state": "01",
        "county": "001",
    }


def test_geoid_is_state_plus_county():
    geo = GEOGRAPHIES["county"]
    assert build_geoid(geo, _county_row()) == "01001"


def test_geoid_tract_concatenates_hierarchy():
    geo = GEOGRAPHIES["tract"]
    row = {"state": "01", "county": "001", "tract": "020100"}
    assert build_geoid(geo, row) == "01001020100"


def test_transform_promotes_typed_columns():
    geo = GEOGRAPHIES["county"]
    rec = transform_row(_county_row(), dataset="acs/acs5", year=2022, geo=geo)
    assert rec.geoid == "01001"
    assert rec.name == "Autauga County, Alabama"
    assert rec.promoted["total_population"] == 58805
    assert rec.promoted["median_household_income"] == 67565


def test_raw_payload_retains_unpromoted_fields():
    geo = GEOGRAPHIES["county"]
    rec = transform_row(_county_row(), dataset="acs/acs5", year=2022, geo=geo)
    # Un-promoted fields survive verbatim in the JSONB payload.
    assert rec.raw["B25001_001E"] == "24571"
    assert "B11001_001E" in rec.raw


def test_jam_sentinels_become_null():
    assert coerce_numeric("-666666666") is None
    assert coerce_numeric("-888888888") is None
    assert coerce_numeric("") is None
    assert coerce_numeric(None) is None
    assert coerce_numeric("42") == 42


def test_db_params_flatten_promoted_and_raw():
    geo = GEOGRAPHIES["county"]
    rec = transform_row(_county_row(), dataset="acs/acs5", year=2022, geo=geo)
    params = record_as_db_params(rec)
    assert params["geoid"] == "01001"
    assert params["total_population"] == 58805
    assert params["raw"]["NAME"].startswith("Autauga")
