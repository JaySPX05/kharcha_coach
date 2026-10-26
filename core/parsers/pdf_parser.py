import io
import re

import pandas as pd
import pdfplumber
import pikepdf

from core.parsers.common import StatementError, add_rows, map_columns, parse_date, to_frame

NUMERIC_FIELDS = {"debit", "credit", "amount", "balance"}
AMOUNT_WORD = re.compile(r"^\(?-?[\d,]+\.\d{2}\)?(Cr|Dr)?$", re.I)
HEADER_WORD_GAP = 8  # pt; words closer than this form one header ("Withdrawal Amt.")
# Lines box each column but not the rows (HDFC): columns from the boxes, rows from text lines.
# The boxes are the true column borders; headers can sit off-centre from their column's text.
COLUMN_BOXES = {"vertical_strategy": "lines", "horizontal_strategy": "text"}


def _column_edges(page) -> list[float] | None:
    """x positions of invisible column lines for an unruled table, found from its header row.

    Text columns start at their header's left edge. Number columns are right-aligned, so a
    number column starts where its widest number starts.
    """
    words = page.extract_words()
    rows: dict[int, list[dict]] = {}
    for w in words:
        rows.setdefault(round(w["top"]), []).append(w)
    for line in rows.values():
        line.sort(key=lambda w: w["x0"])
        groups = [[line[0]]]
        for w in line[1:]:
            if w["x0"] - groups[-1][-1]["x1"] < HEADER_WORD_GAP:
                groups[-1].append(w)
            else:
                groups.append([w])
        cols = map_columns([" ".join(w["text"] for w in g) for g in groups])
        if not cols:
            continue
        numeric = {i for f, i in cols.items() if f in NUMERIC_FIELDS}
        amounts = [w for w in words if AMOUNT_WORD.match(w["text"])]
        # outer lines must touch the text, or pdfplumber drops the edge columns
        edges = [min(w["x0"] for w in words) - 1]
        for i in range(1, len(groups)):
            x0, right = groups[i][0]["x0"], groups[i][-1]["x1"]
            if i in numeric:
                starts = [w["x0"] for w in amounts if abs(w["x1"] - right) < 3]
                x0 = min(starts + [x0])
                if i - 1 in numeric:  # two number columns: don't cut into the previous one
                    x0 = max(x0, groups[i - 1][-1]["x1"] + 1)
            edges.append(x0 - 1)
        return edges + [max(w["x1"] for w in words) + 1]
    return None


def _collapsed(tables: list) -> bool:
    """True if a 'ruled' table packed many transactions into one cell: the lines only box the
    columns (HDFC style), so rows must come from text lines instead."""
    return any(sum(parse_date(line) is not None for line in str(cell or "").splitlines()) >= 2
               for table in tables for row in table for cell in row)


def _decrypt(data: bytes, password: str | None) -> bytes:
    """Return unencrypted PDF bytes; friendly errors for missing/wrong password or broken files."""
    try:
        with pikepdf.open(io.BytesIO(data), password=password or "") as pdf:
            if not pdf.is_encrypted:
                return data
            out = io.BytesIO()
            pdf.save(out, encryption=False)
            return out.getvalue()
    except pikepdf.PasswordError:
        if password:
            raise StatementError("Wrong password for this PDF. Banks often use your DOB or customer ID.") from None
        raise StatementError("This PDF is password-protected. Please enter its password.") from None
    except pikepdf.PdfError:
        raise StatementError("This file isn't a readable PDF. It may be damaged.") from None


def parse_pdf(data: bytes, password: str | None = None) -> pd.DataFrame:
    """Text PDF with a ruled or unruled transaction table -> transactions."""
    data = _decrypt(data, password)
    records: list[dict] = []
    cols = None
    edges = None
    has_text = False
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            has_text = has_text or bool(page.chars)
            settings = None  # ruled table: split cells along its drawn lines
            if page.lines or page.rects:
                if _collapsed(page.extract_tables()):
                    settings = COLUMN_BOXES
            else:  # unruled (common in real banks): invisible lines from the header positions
                edges = _column_edges(page) or edges  # pages without a header reuse the last layout
                if not edges:
                    continue
                settings = {"vertical_strategy": "explicit", "explicit_vertical_lines": edges,
                            "horizontal_strategy": "text"}
            for table in page.extract_tables(settings):
                start = 0
                for i, row in enumerate(table):
                    header = map_columns(row)
                    if header:  # header usually repeats on every page
                        cols, start = header, i + 1
                if cols:
                    add_rows(cols, table[start:], records)
    if not has_text:
        raise StatementError("This PDF looks scanned (no text inside). Download the statement from net banking instead.")
    if cols is None:
        raise StatementError("This bank's PDF layout isn't supported yet. Try the CSV export from net banking.")
    return to_frame(records)
