import io

import pandas as pd
import pikepdf
import pytest
from fpdf import FPDF

from core.parsers import StatementError, parse_statement
from core.parsers.common import parse_amount, parse_date
from scripts.make_synthetic import write_pdf
from tests.conftest import SAMPLE


@pytest.mark.parametrize("text, expected", [
    ("14/09/26", "2026-09-14"), ("14/09/2026", "2026-09-14"), ("14-Sep-2026", "2026-09-14"),
    ("14-SEP-26", "2026-09-14"), ("14 Sep 2026", "2026-09-14"), ("2026-09-14", "2026-09-14"),
    ("14.09.2026", "2026-09-14"), ("14/09/26 10:22:01", "2026-09-14"),
    ("OPENING BALANCE", None), ("", None), (None, None),
])
def test_parse_date(text, expected):
    assert parse_date(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("1,23,456.78", 123456.78), ("349", 349.0), ("349.00 Dr", -349.0), ("349.00Cr", 349.0),
    ("(349.00)", -349.0), ("-349.00", -349.0), ("₹ 1,000.00", 1000.0),
    ("", None), ("-", None), (None, None), ("abc", None),
])
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


def test_samples_round_trip_to_ground_truth(sample):
    truth, parsed, _, _ = sample
    assert len(parsed) == len(truth)
    for col in ("txn_id", "date", "amount", "direction", "balance"):
        assert (parsed[col].values == truth[col].values).all(), col
    # PDF wrapping can change spaces; everything else must match exactly
    squash = lambda s: s.str.replace(r"\s+", "", regex=True)  # noqa: E731
    assert (squash(parsed["narration"]) == squash(truth["narration"])).all()


BANK_CSV = b"""Synthetic Bank Statement
Account No,XXXXXXXX4321
,
Txn Date,Value Date,Description,Ref No,Withdrawal Amt.,Deposit Amt.,Closing Balance
01/09/26,01/09/26,OPENING BALANCE,,,,"10,000.00"
02/09/26,02/09/26,UPI/DR/412345678901/SWIGGY/YESB/,,349.00,,"9,651.00"
,,swiggy@ybl/Payment,,,,
03/09/26,03/09/26,NEFT/CR/HDFCN612345678901/SURESH RAO/HDFC,,,"1,20,000.00","1,29,651.00"
,
Statement Summary,,,,,,
"""


def test_bank_style_csv():
    df = parse_statement(BANK_CSV, "hdfc.csv")
    assert df[["date", "amount", "direction", "balance"]].values.tolist() == [
        ["2026-09-02", 349.0, "debit", 9651.0],
        ["2026-09-03", 120000.0, "credit", 129651.0],
    ]
    assert df["narration"][0] == "UPI/DR/412345678901/SWIGGY/YESB/swiggy@ybl/Payment"  # continuation joined


def test_signed_amount_with_drcr_column():
    data = b"Date,Narration,Amount,Dr/Cr,Balance\n14-Sep-2026,ATM WDL/1/BLR,500,DR,100\n15-Sep-2026,IMPS/P2A/1/X/y,50,CR,150\n"
    df = parse_statement(data, "a.csv")
    assert df["direction"].tolist() == ["debit", "credit"]


def test_identical_rows_get_distinct_stable_ids():
    data = b"Date,Narration,Debit,Credit,Balance\n14/09/26,CHAI,20,,80\n14/09/26,CHAI,20,,60\n"
    a, b = parse_statement(data, "a.csv"), parse_statement(data, "a.csv")
    assert a["txn_id"].is_unique and a["txn_id"].tolist() == b["txn_id"].tolist()


@pytest.fixture(scope="module")
def small_pdf(tmp_path_factory) -> bytes:
    path = tmp_path_factory.mktemp("pdf") / "small.pdf"
    write_pdf(pd.read_csv(SAMPLE / "statement.csv").head(5), path, "%d/%m/%y")
    return path.read_bytes()


def _encrypt(data: bytes, password: str) -> bytes:
    out = io.BytesIO()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        pdf.save(out, encryption=pikepdf.Encryption(owner=password, user=password, R=6))
    return out.getvalue()


def test_password_protected_pdf(small_pdf):
    locked = _encrypt(small_pdf, "01012005")
    with pytest.raises(StatementError, match="password-protected"):
        parse_statement(locked, "s.pdf")
    with pytest.raises(StatementError, match="Wrong password"):
        parse_statement(locked, "s.pdf", password="nope")
    assert len(parse_statement(locked, "s.pdf", password="01012005")) == 5


def test_scanned_pdf_is_rejected():
    pdf = FPDF()
    pdf.add_page()
    pdf.rect(10, 10, 100, 100)  # an image-like page with no text
    with pytest.raises(StatementError, match="scanned"):
        parse_statement(bytes(pdf.output()), "scan.pdf")


@pytest.mark.parametrize("data, name, message", [
    (b"", "a.pdf", "empty"),
    (b"   \n", "a.csv", "empty"),
    (b"PK\x03\x04", "a.xlsx", "Unsupported file type"),
    (b"%PDF-1.4 garbage", "a.pdf", "isn't a readable PDF"),
    (b"name,age\nx,1\n", "a.csv", "Couldn't find the transaction table"),
    (b"Date,Narration,Debit,Credit,Balance\n", "a.csv", "No transactions found"),
])
def test_friendly_errors(data, name, message):
    with pytest.raises(StatementError, match=message):
        parse_statement(data, name)


@pytest.mark.parametrize("stem, date_fmt", [("statement", "%d/%m/%y"), ("statement_b", "%d-%b-%Y")])
def test_unruled_pdf_round_trips(tmp_path, stem, date_fmt):
    """Many real bank PDFs have no table lines; columns come from header positions instead."""
    truth = pd.read_csv(SAMPLE / f"{stem}.csv").head(120)  # ~5 pages: crosses page breaks, stays fast
    path = tmp_path / "unruled.pdf"
    write_pdf(truth, path, date_fmt, ruled=False)
    parsed = parse_statement(path.read_bytes(), "unruled.pdf")
    assert parsed["txn_id"].tolist() == truth["txn_id"].tolist()
    assert parsed["balance"].tolist() == truth["balance"].tolist()


def test_column_boxes_pdf_round_trips(tmp_path):
    """HDFC draws one box per column and no row lines: a plain table read puts a whole page in one row."""
    truth = pd.read_csv(SAMPLE / "statement_b.csv").head(60)
    path = tmp_path / "boxes.pdf"
    write_pdf(truth, path, "%d/%m/%y", ruled=False, column_boxes=True)
    parsed = parse_statement(path.read_bytes(), "boxes.pdf")
    assert parsed["txn_id"].tolist() == truth["txn_id"].tolist()


def test_glued_header_words():
    """Some PDFs lose the space inside a header: 'WithdrawalAmt.', 'ClosingBalance'."""
    from core.parsers.common import map_columns
    header = ["Date", "Narration", "Chq./Ref.No.", "ValueDt", "WithdrawalAmt.", "DepositAmt.", "ClosingBalance"]
    assert map_columns(header) == {"date": 0, "narration": 1, "debit": 4, "credit": 5, "balance": 6}


def test_misread_rows_are_refused_not_returned():
    good = ["Date,Narration,Debit,Credit,Balance", "01/09/26,A,,1000,1000"]
    good += [f"{d:02d}/09/26,UPI/DR/{d}/X/YESB/x@ybl/P,10,,{1000 - 10 * (d - 1)}" for d in range(2, 12)]
    assert len(parse_statement("\n".join(good).encode(), "a.csv")) == 11
    broken = [r.replace(",10,,", ",100,,") if i % 2 else r for i, r in enumerate(good)]  # wrong amounts
    with pytest.raises(StatementError, match="balance doesn't add up"):
        parse_statement("\n".join(broken).encode(), "a.csv")


def test_newest_first_statement_is_accepted():
    data = b"Date,Narration,Debit,Credit,Balance\n03/09/26,C,10,,970\n02/09/26,B,10,,980\n01/09/26,A,10,,990\n"
    assert parse_statement(data, "a.csv")["balance"].tolist() == [970.0, 980.0, 990.0]
