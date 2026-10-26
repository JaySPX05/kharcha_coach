"""Upload -> parse -> decode -> redact -> categorise, as one function.

Kept outside main.py so scripts and tests can run the exact pipeline the app runs.
"""
from __future__ import annotations

from typing import Callable

import pandas as pd

from core.parsers import parse_statement
from core.redact import redact
from core.upi import decode_upi
from llm.categorize import categorize

STEPS = ["Reading statement", "Decoding UPI narrations", "Masking personal data",
         "Categorising merchants (Nemotron Nano)"]


def run_pipeline(file_bytes: bytes, filename: str, password: str | None = None, *,
                 use_llm: bool = True, on_step: Callable[[int, str], None] | None = None) -> pd.DataFrame:
    """Statement bytes -> redacted, categorised transactions. Insights are computed per month by the caller."""
    def step(i: int, fn, *a, **kw):
        if on_step:
            on_step(i, STEPS[i])
        return fn(*a, **kw)

    df = step(0, parse_statement, file_bytes, filename, password)
    df = step(1, decode_upi, df)
    df = step(2, redact, df)          # PII stops here — everything below sees redacted data only
    return step(3, categorize, df, use_llm=use_llm)
