"""Unit tests for the PUMS transform — no DB or network."""
from pgbigdata.pums.transform import (
    INSERT_COLUMNS,
    record_as_db_params,
    transform_row,
)
from pgbigdata.pums.variables import coerce_int, coerce_text, get_param


def _row():
    # Mirrors a real PUMS API row (the 'state' col comes from for=state:56).
    return {
        "SERIALNO": "2022GQ0000581",
        "SPORDER": "1",
        "PUMA": "00500",
        "PWGTP": "25",
        "AGEP": "43",
        "SEX": "1",
        "RAC1P": "1",
        "HISP": "01",
        "SCHL": "17",
        "ESR": "2",
        "COW": "1",
        "WKHP": "40",
        "JWMNP": "15",
        "OCCP": "4700",
        "INDP": "8680",
        "PINCP": "20000",
        "WAGP": "20000",
        "HICOV": "1",
        "state": "56",
    }


def test_key_and_geo():
    rec = transform_row(_row(), dataset="acs/acs1/pums", year=2022)
    assert rec.serialno == "2022GQ0000581"
    assert rec.sporder == 1
    assert rec.st == "56"
    assert rec.promoted["puma"] == "00500"


def test_promoted_typed_values():
    rec = transform_row(_row(), dataset="acs/acs1/pums", year=2022)
    assert rec.promoted["pwgtp"] == 25
    assert rec.promoted["agep"] == 43
    assert rec.promoted["pincp"] == 20000
    assert rec.promoted["sex"] == "1"


def test_leading_zero_codes_preserved():
    rec = transform_row(_row(), dataset="acs/acs1/pums", year=2022)
    # Categorical codes stay text — leading zeros must survive.
    assert rec.promoted["puma"] == "00500"
    assert rec.promoted["hisp"] == "01"


def test_negative_income_not_nullified():
    # PUMS income can be a loss; unlike aggregate ACS, negatives are kept.
    assert coerce_int("-5000") == -5000
    assert coerce_int("") is None
    assert coerce_text("") is None
    assert coerce_text("00500") == "00500"


def test_db_params_cover_all_insert_columns():
    rec = transform_row(_row(), dataset="acs/acs1/pums", year=2022)
    params = record_as_db_params(rec)
    # Every column the upsert references (except raw timestamp) must be present.
    for col in INSERT_COLUMNS:
        assert col in params, f"missing {col}"
    assert params["raw"]["SERIALNO"] == "2022GQ0000581"


def test_get_param_under_50_vars():
    assert len(get_param().split(",")) < 50
