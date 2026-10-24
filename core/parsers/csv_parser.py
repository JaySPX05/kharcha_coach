import csv
import io

import pandas as pd

from core.parsers.common import StatementError, add_rows, map_columns, to_frame

_HEADER_SEARCH_ROWS = 60  # banks put account details above the table


def parse_csv(data: bytes) -> pd.DataFrame:
    """Bank CSV export or our own schema CSV -> transactions."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    rows = list(csv.reader(io.StringIO(text)))
    for i, row in enumerate(rows[:_HEADER_SEARCH_ROWS]):
        cols = map_columns(row)
        if cols:
            records: list[dict] = []
            add_rows(cols, rows[i + 1:], records)
            return to_frame(records)
    raise StatementError(
        "Couldn't find the transaction table in this CSV. Expected columns like "
        "Date, Narration/Description, Debit/Withdrawal, Credit/Deposit, Balance."
    )
