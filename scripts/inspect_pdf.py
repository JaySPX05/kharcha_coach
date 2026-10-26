"""Show a statement PDF's table layout without showing personal data, to debug the parser.

Run:  python scripts/inspect_pdf.py "D:\\statements\\my.pdf"
Prints header lines, dates and amounts as they are. Every other letter becomes A/a and every
other digit 9, keeping known words like UPI/NEFT/DR. Safe to paste into a chat or an issue.
"""
import getpass
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import io  # noqa: E402

import pdfplumber  # noqa: E402

from core.parsers.common import StatementError, map_columns, parse_date  # noqa: E402
from core.parsers.pdf_parser import AMOUNT_WORD, HEADER_WORD_GAP, _decrypt  # noqa: E402

VOCAB = {"date", "txn", "tran", "transaction", "value", "narration", "description", "particulars", "remarks",
         "details", "debit", "credit", "withdrawal", "withdrawals", "deposit", "deposits", "amount", "amt",
         "balance", "closing", "chq", "cheque", "ref", "dr", "cr", "type", "inr"}
KEEP = {"UPI", "NEFT", "IMPS", "RTGS", "DR", "CR", "ATM", "POS", "ECOM", "NWD", "ATW", "CHQ", "DEP", "INB",
        "TO", "BY", "TRANSFER", "ACH", "NACH", "BIL", "ONL", "INT", "PAYMENT", "CASH", "WDL", "P2A", "P2M",
        "OPENING", "CLOSING", "BALANCE", "TOTAL", "PAGE", "OF"}


def mask(text) -> str:
    s = " ".join(str(text or "").split())
    # only a whole cell that is just a date or a money amount (with paise) is shown as is;
    # "01/09/26 UPI-..." or a bare 12-digit reference number is masked like everything else
    if not s or (parse_date(s) and len(s) <= 11) or AMOUNT_WORD.match(s.replace(" ", "")):
        return s
    s = re.sub(r"[A-Za-z]+", lambda m: m.group() if m.group().upper() in KEEP else
               re.sub("[a-z]", "a", re.sub("[A-Z]", "A", m.group())), s)
    return re.sub(r"\d", "9", s)


HEADER_WORDS = VOCAB | {"no", "s", "sl", "dt", "num", "number", "init", "br", "of", "available", "particular"}


def header_cell(cell) -> bool:
    """Shown as is only if every word in it is a header word ('Withdrawal Amt.', 'Chq./Ref.No.')."""
    words = re.findall(r"[a-z]+", str(cell or "").lower())
    return bool(words) and all(w in HEADER_WORDS for w in words)


def is_header(cells) -> bool:
    # data rows carry dates, amounts or VPAs; a header row has none of those
    text = " ".join(str(c or "") for c in cells)
    return not re.search(r"[\d@]", text) and len(VOCAB & set(re.findall(r"[a-z]+", text.lower()))) >= 2


def show(cells, header: bool) -> list:
    return [c if header and header_cell(c) else mask(c) for c in cells]


def main(path: str) -> None:
    data = Path(path).read_bytes()
    try:
        data = _decrypt(data, None)
    except StatementError:
        data = _decrypt(data, getpass.getpass("PDF password (not shown): "))
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        print(f"pages: {len(pdf.pages)}")
        for n, page in enumerate(pdf.pages[:2], 1):
            print(f"\n===== page {n}: {len(page.chars)} chars, {len(page.lines)} lines, {len(page.rects)} rects "
                  f"-> {'ruled' if page.lines or page.rects else 'unruled'}")
            # what the unruled path sees: words grouped into cells line by line
            rows: dict[int, list] = {}
            for w in page.extract_words():
                rows.setdefault(round(w["top"]), []).append(w)
            shown = 0
            for top in sorted(rows):
                line = sorted(rows[top], key=lambda w: w["x0"])
                groups = [[line[0]]]
                for w in line[1:]:
                    (groups[-1].append(w) if w["x0"] - groups[-1][-1]["x1"] < HEADER_WORD_GAP else groups.append([w]))
                cells = [" ".join(w["text"] for w in g) for g in groups]
                if is_header(cells):
                    print(f"HEADER? y={top} x={[round(g[0]['x0']) for g in groups]}")
                    print(f"   cells: {show(cells, True)}")
                    print(f"   map_columns -> {map_columns(cells)}")
                    shown = 6
                elif shown:
                    print(f"   row: {[mask(c) for c in cells]}")
                    shown -= 1
            tables = page.extract_tables()
            print(f"extract_tables (default): {len(tables)} table(s) {[f'{len(t)}x{len(t[0]) if t else 0}' for t in tables]}")
            for t in tables[:2]:
                for row in t[:6]:
                    print(f"   cells: {show(row, is_header(row))}")
    parsed(data)


def parsed(data: bytes) -> None:
    """What the parser and decoder made of the rows, masked the same way."""
    from collections import Counter

    from core.parsers.pdf_parser import COLUMN_BOXES, _collapsed, _column_edges, parse_pdf
    from core.upi import PATTERNS, decode_upi

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        page = pdf.pages[0]
        settings = None  # same choice parse_pdf makes for this page
        if page.lines or page.rects:
            if _collapsed(page.extract_tables()):
                settings = COLUMN_BOXES
        elif edges := _column_edges(page):
            settings = {"vertical_strategy": "explicit", "explicit_vertical_lines": edges, "horizontal_strategy": "text"}
        print(f"\n===== column cut on page 1: {settings}")
        for t in page.extract_tables(settings)[:1]:
            start = next((i for i, r in enumerate(t) if map_columns(r)), -1) + 1
            for row in t[start:start + 6]:
                print(f"   cells: {show(row, False)}")
    df = decode_upi(parse_pdf(data))
    print(f"\n===== parsed {len(df)} rows; channel {dict(Counter(df['channel']))}; cp_type {dict(Counter(df['cp_type']))}")
    for _, r in df[df["direction"] == "debit"].head(8).iterrows():
        text = " ".join(str(r["narration"]).split())
        hit = next((i for i, rx in enumerate(PATTERNS.get(r["channel"], ())) if rx.search(text)), None)
        print(f"   {r['channel']:5} {r['cp_type']:8} pattern={hit} | {mask(text)}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit('usage: python scripts/inspect_pdf.py "path\\to\\statement.pdf"')
    main(sys.argv[1])
