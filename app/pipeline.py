"""Upload -> parse -> decode -> redact -> categorise -> insights, as one function.

Kept outside main.py so scripts and tests can run the exact pipeline the app runs.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from core.insights import compute_insights
from core.parsers import parse_statement
from core.redact import redact
from core.upi import decode_upi
from llm.categorize import categorize

STEPS = ["Reading statement", "Decoding UPI narrations", "Masking personal data",
         "Categorising merchants (Nemotron Nano)", "Computing insights"]


@dataclass
class PipelineResult:
    df: pd.DataFrame
    insights: dict
    timings: dict = field(default_factory=dict)
    sent_to_nano: list[str] = field(default_factory=list)


def run_pipeline(file_bytes: bytes, filename: str, password: str | None = None, *,
                 use_llm: bool = True, on_step: Callable[[int, str], None] | None = None) -> PipelineResult:
    timings: dict[str, float] = {}

    def step(i: int, fn, *a, **kw):
        if on_step:
            on_step(i, STEPS[i])
        t = time.perf_counter()
        out = fn(*a, **kw)
        timings[STEPS[i]] = round(time.perf_counter() - t, 2)
        return out

    df = step(0, parse_statement, file_bytes, filename, password)
    df = step(1, decode_upi, df)
    df = step(2, redact, df)          # PII stops here — everything below sees redacted data only
    df = step(3, categorize, df, use_llm=use_llm)
    insights = step(4, compute_insights, df)
    sent = sorted({str(c) for c in df.loc[df["category_source"] == "llm", "counterparty"]})
    return PipelineResult(df=df, insights=insights, timings=timings, sent_to_nano=sent)
