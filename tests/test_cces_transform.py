"""Unit tests for the CCES transform — no DB or network."""
from pgbigdata.cces.transform import (
    CONFLICT_COLUMNS,
    INSERT_COLUMNS,
    record_as_db_params,
    transform_row,
)
from pgbigdata.cces.variables import coerce


def _row():
    return {
        "caseid": "123456789",
        "commonweight": "0.8423",
        "commonpostweight": "0.9011",
        "vvweight": "",            # missing -> NULL
        "inputstate": "6",         # CA, no leading zero
        "countyfips": "6085",      # Santa Clara, leading zero dropped
        "cdid116": "CA-17",
        "birthyr": "1985",
        "gender": "2",
        "educ": "5",
        "race": "1",
        "hispanic": "2",
        "marstat": "1",
        "votereg": "1",
        "pid3": "1",
        "pid7": "2",
        "ideo5": "2",
        "CC18_308a": "3",          # a survey item -> stays in JSONB only
    }


def test_key_and_types():
    rec = transform_row(_row(), dataset="cces", year=2018)
    assert rec.caseid == 123456789
    assert rec.promoted["commonweight"] == 0.8423
    assert rec.promoted["birthyr"] == 1985


def test_missing_weight_is_null():
    rec = transform_row(_row(), dataset="cces", year=2018)
    assert rec.promoted["vvweight"] is None


def test_crosswalk_keys_kept_as_text():
    rec = transform_row(_row(), dataset="cces", year=2018)
    # countyfips stays text so we can lpad it to the 5-digit ACS geoid later.
    assert rec.promoted["countyfips"] == "6085"
    assert rec.promoted["inputstate"] == "6"


def test_column_aliases_across_years():
    # 2018 names: gender / cdid116
    r18 = transform_row(_row(), dataset="cces", year=2018)
    assert r18.promoted["gender"] == "2"
    assert r18.promoted["cd"] == "CA-17"
    # 2022/2024 names: gender4 / cdid118 — same destination columns
    r24 = transform_row(
        {"caseid": "9", "gender4": "1", "cdid118": "TX-02"},
        dataset="cces", year=2024,
    )
    assert r24.promoted["gender"] == "1"
    assert r24.promoted["cd"] == "TX-02"


def test_survey_items_only_in_jsonb():
    rec = transform_row(_row(), dataset="cces", year=2018)
    assert "CC18_308a" not in rec.promoted          # not promoted
    assert rec.raw["CC18_308a"] == "3"              # but retained in raw


def test_coerce_helpers():
    assert coerce("bigint", "42") == 42
    assert coerce("float", "1.5") == 1.5
    assert coerce("int", "") is None
    assert coerce("text", " x ") == "x"
    assert coerce("float", "not-a-number") is None


def test_db_params_cover_insert_columns():
    rec = transform_row(_row(), dataset="cces", year=2018)
    params = record_as_db_params(rec)
    for col in INSERT_COLUMNS:
        assert col in params
    for col in CONFLICT_COLUMNS:
        assert col in params
