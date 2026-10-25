"""Check that every number a model wrote came from our pandas results.

The models are told to only quote numbers from tool results / insights. This is
the seatbelt: pull every number out of the model's text and flag any that is not
in (or a simple sum/difference of numbers in) the source data.
"""
from __future__ import annotations

import itertools
import re
from typing import Any, Iterable

_NUM = re.compile(r"(?<![A-Za-z_])\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|(?<![A-Za-z_])\d+(?:\.\d+)?")
MAX_PAIR_SOURCE = 400  # cap so pairwise sums stay cheap


def numbers_in(obj: Any) -> list[float]:
    """Every number inside a nested dict/list/str structure."""
    out: list[float] = []
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, str):
        out += [float(m.replace(",", "")) for m in _NUM.findall(obj)]
    elif isinstance(obj, dict):
        for v in obj.values():
            out += numbers_in(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out += numbers_in(v)
    return out


def _close(a: float, allowed: Iterable[float]) -> bool:
    for b in allowed:
        if abs(a - b) <= max(1.0, abs(b) * 0.005):  # allow rounding: 5,998.5 -> 5,999; 21.4% -> 21%
            return True
    return False


def unverified_numbers(text: str, source: Any, *, allow_small: int = 31) -> list[str]:
    """Numbers in `text` that are not in `source` or a sum/difference of two of them.

    Small integers (<= 31: counts, days, "3 actions") and years are allowed.
    """
    src = sorted({abs(x) for x in numbers_in(source)})
    pool = set(src)
    top = sorted(src, reverse=True)[:MAX_PAIR_SOURCE]
    for a, b in itertools.combinations(top, 2):
        pool.add(a + b)
        pool.add(abs(a - b))
    pool = sorted(pool)

    flagged = []
    for raw in _NUM.findall(text or ""):
        val = float(raw.replace(",", ""))
        if val <= allow_small or 2000 <= val <= 2100 and val == int(val):
            continue
        if not _close(val, pool):
            flagged.append(raw)
    return flagged


def format_inr(x: float, decimals: int = 0) -> str:
    """12345678.9 -> '1,23,45,679' (Indian digit grouping)."""
    neg = x < 0
    x = abs(round(x, decimals))
    whole, _, frac = f"{x:.{decimals}f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        head = ",".join(re.findall(r"\d{1,2}(?=(?:\d{2})*$)", head))
        whole = f"{head},{tail}"
    s = whole + (f".{frac}" if frac else "")
    return ("-" if neg else "") + s
