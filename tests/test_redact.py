import pandas as pd

from core.redact import redact
from core.schema import validate
from core.upi import decode_upi
from scripts.make_synthetic import PEOPLE

TEXT_COLS = ["narration", "counterparty", "vpa"]


def test_no_long_digit_run_survives(sample):
    *_, redacted = sample
    text = redacted[TEXT_COLS].fillna("").astype(str)
    assert not text.apply(lambda s: s.str.contains(r"\d{10}")).any().any()


def test_no_real_person_names_survive(sample):
    *_, redacted = sample
    blob = " ".join(redacted[TEXT_COLS].fillna("").astype(str).values.ravel()).upper().replace(" ", "")
    for name, vpa, _ in PEOPLE.values():
        assert name.upper().replace(" ", "") not in blob
        if vpa:
            assert vpa.split("@")[0].upper() not in blob


def test_aliases_and_vpas_match_ground_truth(sample):
    truth, *_, redacted = sample
    validate(redacted)
    people = truth["cp_type"] == "person"
    assert (redacted["counterparty"][people].values == truth["counterparty"][people].values).all()
    assert (redacted["vpa"][people].fillna("").values == truth["vpa"][people].fillna("").values).all()


def test_merchants_stay_readable(sample):
    _, _, decoded, redacted = sample
    merchants = decoded["cp_type"] == "merchant"
    assert (redacted["counterparty"][merchants] == decoded["counterparty"][merchants]).all()
    assert "Swiggy" in set(redacted["counterparty"])


def test_same_person_same_alias_across_channels():
    df = decode_upi(pd.DataFrame({"narration": [
        "UPI/DR/412345678901/RAHUL KUMAR/UTIB/rahul.k@okaxis/dinner",
        "IMPS/P2A/612345678901/RAHUL KUMAR/trip",
        "UPI/DR/412345678902/RAHULKUMAR/UTIB/rahul.k@okaxis/auto",  # glued by PDF wrap
        "UPI/CR/412345678903/PRIYA SHARMA/HDFC/9000023456@ybl/thanks",
    ]}))
    out = redact(df)
    assert out["counterparty"].tolist() == ["Person_01", "Person_01", "Person_01", "Person_02"]
    assert out["vpa"].tolist()[3] == "person_02@ybl"
    assert out["narration"][1] == "IMPS/P2A/XXXXXXXX8901/Person_01/trip"


def test_input_not_modified():
    df = decode_upi(pd.DataFrame({"narration": ["UPI/CR/412345678903/PRIYA SHARMA/HDFC/9000023456@ybl/x"]}))
    before = df.copy()
    redact(df)
    pd.testing.assert_frame_equal(df, before)
