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
        if abs(a - b) <= 1.0:  # rounding to whole rupees / whole percent only; "about 8,000" for 8,048 is flagged
            return True
    return False


def unverified_numbers(text: str, source: Any, *, allow_small: int = 31) -> list[str]:
    """Numbers in `text` that can't be traced to `source`.

    A number is traced if it is in `source` (within rounding), or is the sum or
    difference of two numbers that the text itself quotes and that are traced
    ("from Rs 3,007 to Rs 5,999, up Rs 2,992"). Pairs are limited to numbers
    quoted in the text: with hundreds of source numbers, almost any round figure
    is *some* difference by chance. Small integers (<= 31: counts, days) and
    years are always allowed.
    """
    src = sorted({abs(x) for x in numbers_in(source)})
    found = [(raw, float(raw.replace(",", ""))) for raw in _NUM.findall(text or "")]

    def trivial(v: float) -> bool:
        return v <= allow_small

    direct = [v for _, v in found if not trivial(v) and _close(v, src)]
    derived = {a + b for a, b in itertools.combinations(direct, 2)} | \
              {abs(a - b) for a, b in itertools.combinations(direct, 2)}

    flagged = []
    for raw, val in found:
        if raw.isdigit() and 2000 <= val <= 2100 and len(raw) == 4:
            continue  # a year
        if val <= allow_small or _close(val, src) or _close(val, derived):
            continue
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
