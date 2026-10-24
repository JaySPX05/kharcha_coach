"""Transaction schema shared by core/ and llm/. See CLAUDE.md section 4."""

import hashlib

import pandas as pd

COLUMNS: tuple[str, ...] = (
    "txn_id",
    "date",
    "narration",
    "amount",
    "direction",
    "balance",
    "channel",
    "counterparty",
    "vpa",
    "cp_type",
    "category",
    "category_source",
)

DIRECTIONS = ("debit", "credit")
CHANNELS = ("UPI", "NEFT", "IMPS", "CARD", "ATM", "OTHER")
CP_TYPES = ("merchant", "person", "unknown")
CATEGORY_SOURCES = ("rule", "llm", "cache", "user")
CATEGORIES = (
    "Food delivery",
    "Groceries",
    "Eating out",
    "Transport",
    "Fuel",
    "Shopping",
    "Subscriptions",
    "Bills & recharge",
    "Rent",
    "Education",
    "Health",
    "Entertainment",
    "Travel",
    "Transfers to people",
    "Cash withdrawal",
    "Investments",
    "Income",
    "Other",
)

_MAX_ROWS_SHOWN = 5


def make_txn_id(date: str, amount: float, direction: str, narration: str) -> str:
    """Stable id so re-uploading the same statement doesn't duplicate rows.

    Whitespace is ignored because PDF line-wrapping can drop or add spaces in a narration.
    """
    key = f"{pd.Timestamp(date):%Y-%m-%d}|{float(amount):.2f}|{direction}|{''.join(narration.split())}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _rows(mask: pd.Series) -> str:
    idx = list(mask[mask].index[:_MAX_ROWS_SHOWN])
    more = int(mask.sum()) - len(idx)
    return f"rows {idx}" + (f" (+{more} more)" if more > 0 else "")


def validate(df: pd.DataFrame) -> None:
    """Raise one ValueError listing every schema problem in df; return None if valid."""
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        # Nothing else is checkable without the columns, so stop here.
        raise ValueError(f"Missing columns: {missing}")

    errors: list[str] = []

    ids = df["txn_id"]
    if ids.isna().any():
        errors.append(f"txn_id is empty in {_rows(ids.isna())}")
    dup = ids.duplicated(keep=False) & ids.notna()
    if dup.any():
        errors.append(f"txn_id is duplicated in {_rows(dup)}")

    # CSV gives dates as strings; format="mixed" lets each value parse on its own.
    dates = pd.to_datetime(df["date"], errors="coerce", format="mixed")
    if dates.isna().any():
        errors.append(f"date is missing or unparseable in {_rows(dates.isna())}")

    amount = pd.to_numeric(df["amount"], errors="coerce")
    bad_amount = amount.isna() | (amount <= 0)
    if bad_amount.any():
        errors.append(f"amount must be a positive number in {_rows(bad_amount)}")

    balance = pd.to_numeric(df["balance"], errors="coerce")
    bad_balance = balance.isna() & df["balance"].notna()
    if bad_balance.any():
        errors.append(f"balance must be a number or empty in {_rows(bad_balance)}")

    for col, allowed, nullable in (
        ("direction", DIRECTIONS, False),
        ("channel", CHANNELS, False),
        ("cp_type", CP_TYPES, False),
        ("category", CATEGORIES, True),
        ("category_source", CATEGORY_SOURCES, True),
    ):
        values = df[col]
        bad = ~values.isin(allowed)
        if nullable:
            bad &= values.notna()
        if bad.any():
            examples = sorted({str(v) for v in values[bad]})[:_MAX_ROWS_SHOWN]
            errors.append(f"{col} has values {examples} not in {list(allowed)}; {_rows(bad)}")

    if errors:
        raise ValueError("Schema validation failed:\n- " + "\n- ".join(errors))
