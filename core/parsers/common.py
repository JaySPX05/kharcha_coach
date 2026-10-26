"""Helpers shared by the CSV and PDF parsers: dates, amounts, header mapping, row assembly."""

import re
from collections import Counter
from datetime import datetime

import pandas as pd

from core.schema import COLUMNS, make_txn_id


class StatementError(ValueError):
    """A problem with the uploaded file, with a message safe to show the user."""


DATE_FORMATS = (
    "%d/%m/%y", "%d/%m/%Y", "%d-%m-%y", "%d-%m-%Y", "%d.%m.%y", "%d.%m.%Y",
    "%d-%b-%Y", "%d-%b-%y", "%d %b %Y", "%d %b %y", "%Y-%m-%d",
)

# header text -> field; first key that matches a column wins (checked in this order)
HEADER_KEYS = {
    "date": ("txn date", "transaction date", "tran date", "date"),
    "narration": ("narration", "description", "particulars", "remarks", "details", "transaction details"),
    "drcr": ("dr/cr", "cr/dr", "direction", "type"),
    "debit": ("debit", "withdrawal", "withdrawals", "dr amount"),
    "credit": ("credit", "deposit", "deposits", "cr amount"),
    "amount": ("amount", "transaction amount"),
    "balance": ("balance", "closing balance", "available balance"),
}
SKIP_ROW = re.compile(r"opening balance|closing balance|brought forward|carried forward|^total", re.I)
FOOTER = re.compile(r"page \d+|computer generated|system generated|does not require signature", re.I)


def parse_date(text: object) -> str | None:
    """'14/09/26', '14-Sep-2026', '2026-09-14 10:22' ... -> '2026-09-14'; None if not a date."""
    s = str(text or "").strip()
    for candidate in (s, s.split(" ")[0]):
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(candidate, fmt).date().isoformat()
            except ValueError:
                pass
    return None


def parse_amount(text: object) -> float | None:
    """'1,23,456.78' -> 123456.78; '349.00 Dr' / '(349.00)' / '-349' -> -349.0; blank -> None."""
    s = str(text if text is not None else "").replace("₹", "").replace("INR", "").replace(" ", "").strip()
    if s.lower() in ("", "-", "nan", "none"):
        return None
    sign = 1.0
    if s[-2:].upper() in ("CR", "DR"):
        sign = -1.0 if s[-2:].upper() == "DR" else 1.0
        s = s[:-2]
    if s.startswith("(") and s.endswith(")"):
        sign, s = -sign, s[1:-1]
    try:
        return sign * float(s.replace(",", ""))
    except ValueError:
        return None


def _header_match(name: str, key: str) -> bool:
    """'withdrawal amt.' or glued 'withdrawalamt.' (some PDFs drop the space) both match 'withdrawal'."""
    if name == key or re.match(rf"{re.escape(key)}[ .(]", name):
        return True
    glued, k = name.replace(" ", ""), key.replace(" ", "")
    return glued == k or bool(re.fullmatch(rf"{re.escape(k)}(?:[.(].*|amt\.?|amount.*)", glued))


def map_columns(header: list) -> dict[str, int] | None:
    """Find which column holds which field; None if this row isn't a statement header."""
    names = [" ".join(str(h or "").lower().split()) for h in header]
    cols: dict[str, int] = {}
    for field, keys in HEADER_KEYS.items():
        for i, name in enumerate(names):
            if i in cols.values():
                continue
            if any(_header_match(name, k) for k in keys) or (
                field == "balance" and "balance" in name
            ):
                cols[field] = i
                break
    has_amounts = {"debit", "credit"} <= cols.keys() or "amount" in cols
    return cols if {"date", "narration"} <= cols.keys() and has_amounts else None


def join_lines(text: object) -> str:
    # Wrapped cells lose the info whether a space was at the break; joining tight keeps VPAs intact.
    return "".join(line.strip() for line in str(text or "").splitlines()).strip()


def add_rows(cols: dict[str, int], rows: list[list], records: list[dict]) -> None:
    """Turn raw table rows into transaction records, appending to `records` in place."""
    continuing = False  # True right after a transaction row, so a date-less row can extend it
    for row in rows:
        def cell(field: str):
            i = cols.get(field)
            return row[i] if i is not None and i < len(row) else None

        if not any(str(c or "").strip() for c in row):
            continue  # spacer rows: text-aligned PDF tables have one between every line
        narration = join_lines(cell("narration"))
        day = parse_date(cell("date"))
        debit, credit = parse_amount(cell("debit")), parse_amount(cell("credit"))
        amount = parse_amount(cell("amount"))
        if day is None:
            # multi-line narration split across rows: only text in the narration column
            if FOOTER.search(narration):
                continue  # page footer between a row and its continuation on the next page
            if continuing and narration and debit is None and credit is None and amount is None:
                records[-1]["narration"] += narration
            else:
                continuing = False
            continue
        if SKIP_ROW.search(narration):
            continuing = False
            continue
        if "amount" in cols and amount is not None:
            drcr = str(cell("drcr") or "").strip().upper()
            if drcr.startswith("D") or (not drcr and amount < 0):
                debit, credit = abs(amount), None
            else:
                debit, credit = None, abs(amount)
        if debit:
            direction, value = "debit", abs(debit)
        elif credit:
            direction, value = "credit", abs(credit)
        else:
            continuing = False
            continue
        records.append({"date": day, "narration": narration, "amount": value,
                        "direction": direction, "balance": parse_amount(cell("balance"))})
        continuing = True


def balance_breaks(df: pd.DataFrame) -> int:
    """Rows whose balance != previous balance +/- amount. Works oldest-first or newest-first."""
    bal = df["balance"].astype(float)
    signed = df["amount"].where(df["direction"] == "credit", -df["amount"])
    oldest_first = (bal.shift(1) + signed - bal).abs() > 0.01
    newest_first = (bal.shift(-1) + signed - bal).abs() > 0.01  # NaN comparisons are False
    return int(min(oldest_first.sum(), newest_first.sum()))


def to_frame(records: list[dict]) -> pd.DataFrame:
    """Records -> schema-ordered DataFrame with txn_id; decode/categorise columns left empty.

    Refuses the file if the running balance doesn't add up: that means rows were misread or lost.
    """
    if not records:
        raise StatementError("No transactions found in this file. Is it a bank statement?")
    df = pd.DataFrame(records)
    breaks = balance_breaks(df)
    if breaks > max(2, 0.02 * len(df)):
        raise StatementError(
            f"We read {len(df)} transactions but the balance doesn't add up in {breaks} places, "
            "so some rows were probably misread. Please try the CSV export from net banking."
        )
    seen: Counter = Counter()
    ids = []
    for r in records:
        base = make_txn_id(r["date"], r["amount"], r["direction"], r["narration"])
        seen[base] += 1
        # identical rows (same day, amount, narration) stay distinct and stable across re-uploads
        ids.append(base if seen[base] == 1 else f"{base}-{seen[base]}")
    df["txn_id"] = ids
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[list(COLUMNS)]
