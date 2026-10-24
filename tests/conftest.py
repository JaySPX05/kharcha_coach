from functools import lru_cache
from pathlib import Path

import pandas as pd
import pytest

from core.parsers import parse_statement
from core.redact import redact
from core.upi import decode_upi

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample"
SAMPLES = [(stem, ext) for stem in ("statement", "statement_b") for ext in ("csv", "pdf")]


@lru_cache(maxsize=None)
def _run(stem: str, ext: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(parsed, decoded, redacted) for a sample file; cached because PDF parsing takes seconds."""
    parsed = parse_statement((SAMPLE / f"{stem}.{ext}").read_bytes(), f"{stem}.{ext}")
    decoded = decode_upi(parsed)
    return parsed, decoded, redact(decoded)


@pytest.fixture(params=SAMPLES, ids=lambda p: f"{p[0]}.{p[1]}")
def sample(request):
    """Yields (truth, parsed, decoded, redacted) for each sample file."""
    stem, ext = request.param
    truth = pd.read_csv(SAMPLE / f"{stem}.csv")
    return (truth, *_run(stem, ext))
