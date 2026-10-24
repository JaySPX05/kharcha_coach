from pathlib import Path

import pandas as pd

from core.parsers.common import StatementError
from core.parsers.csv_parser import parse_csv
from core.parsers.pdf_parser import parse_pdf

__all__ = ["StatementError", "parse_statement"]


def parse_statement(file_bytes: bytes, filename: str, password: str | None = None) -> pd.DataFrame:
    """Bank statement bytes -> DataFrame with txn_id, date, narration, amount, direction, balance.

    Other schema columns are present but empty; decode_upi() fills them.
    Raises StatementError with a user-friendly message on bad input.
    """
    if not file_bytes or not file_bytes.strip():
        raise StatementError("The file is empty.")
    ext = Path(filename).suffix.lower()
    if ext == ".pdf" or file_bytes[:5] == b"%PDF-":
        return parse_pdf(file_bytes, password)
    if ext in (".csv", ".txt"):
        return parse_csv(file_bytes)
    raise StatementError(f"Unsupported file type '{ext}'. Upload a PDF or CSV statement.")
