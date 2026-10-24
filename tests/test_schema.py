from pathlib import Path

import pandas as pd
import pytest

from core.schema import CATEGORIES, COLUMNS, make_txn_id, validate
from scripts.make_synthetic import inr, main

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample"
NARRATION = "UPI/DR/412345678901/SWIGGY/YESB/swiggy@ybl/Payment"


def _row(**overrides) -> dict:
    row = {
        "txn_id": make_txn_id("2026-09-14", 349.0, "debit", NARRATION),
        "date": "2026-09-14", "narration": NARRATION, "amount": 349.0, "direction": "debit",
        "balance": 12450.5, "channel": "UPI", "counterparty": "Swiggy", "vpa": "swiggy@ybl",
        "cp_type": "merchant", "category": None, "category_source": None,
    }
    return {**row, **overrides}


def test_valid_frame_passes():
    validate(pd.DataFrame([_row(), _row(txn_id="b", category="Food delivery", category_source="llm",
                                        balance=None)]))


@pytest.mark.parametrize("overrides, message", [
    ({"direction": "out"}, "direction has values ['out']"),
    ({"amount": -5}, "amount must be a positive number"),
    ({"amount": 0}, "amount must be a positive number"),
    ({"date": "not a date"}, "date is missing or unparseable"),
    ({"channel": "PAYTM"}, "channel has values ['PAYTM']"),
    ({"cp_type": "shop"}, "cp_type has values ['shop']"),
    ({"category": "Food"}, "category has values ['Food']"),
    ({"category_source": "guess"}, "category_source has values ['guess']"),
    ({"balance": "abc"}, "balance must be a number or empty"),
    ({"txn_id": None}, "txn_id is empty"),
])
def test_bad_value_is_reported(overrides, message):
    with pytest.raises(ValueError, match=message.replace("[", r"\[").replace("]", r"\]")):
        validate(pd.DataFrame([_row(**overrides)]))


def test_all_problems_reported_together():
    with pytest.raises(ValueError) as exc:
        validate(pd.DataFrame([_row(amount=-1, direction="out", category="Food")]))
    assert str(exc.value).count("\n- ") == 3


def test_duplicate_txn_id():
    with pytest.raises(ValueError, match=r"txn_id is duplicated in rows \[0, 1\]"):
        validate(pd.DataFrame([_row(), _row()]))


def test_missing_column():
    with pytest.raises(ValueError, match=r"Missing columns: \['vpa'\]"):
        validate(pd.DataFrame([_row()]).drop(columns=["vpa"]))


def test_contract_sizes():
    assert len(COLUMNS) == 12 and len(CATEGORIES) == 18


def test_txn_id_is_stable_and_normalised():
    a = make_txn_id("2026-09-14", 349, "debit", NARRATION)
    assert a == "e416e7b2f00a0581"
    assert a == make_txn_id("2026-09-14 00:00:00", 349.0, "debit", NARRATION + "  ")
    assert a != make_txn_id("2026-09-14", 349, "credit", NARRATION)


@pytest.mark.parametrize("value, expected", [
    (0, "0.00"), (999, "999.00"), (1000, "1,000.00"), (123456.78, "1,23,456.78"),
    (12345678, "1,23,45,678.00"),
])
def test_inr(value, expected):
    assert inr(value) == expected


@pytest.mark.parametrize("name", ["statement.csv", "statement_b.csv"])
def test_sample_csv_passes_validate(name):
    df = pd.read_csv(SAMPLE / name)
    validate(df)
    assert df["category"].isna().all() and df["category_source"].isna().all()
    assert (df["balance"] >= 0).all()


def test_generator_is_deterministic_and_matches_committed_sample(tmp_path):
    main(tmp_path / "a")
    main(tmp_path / "b")
    for name in ("statement.csv", "statement_b.csv", "statement.pdf"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
    # committed CSV must be what the generator produces; re-run make_synthetic.py if this fails
    assert (tmp_path / "a" / "statement.csv").read_bytes() == (SAMPLE / "statement.csv").read_bytes()
