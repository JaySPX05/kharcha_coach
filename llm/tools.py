"""The insight helpers exposed to Nemotron Super as callable tools.

Each tool is a thin wrapper over core/insights.py. The model chooses which tool
to call and with what arguments; *we* run pandas and send the result back. The
model only ever sees results, so every number it says has a source.
"""
from __future__ import annotations

import json
from typing import Any, Callable

import pandas as pd

from core import insights as ins
from core.schema import CATEGORIES

MONTH = {"type": "string", "description": "Month as YYYY-MM, e.g. 2026-09. Omit for all months."}

TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "spend_by",
        "description": "Total amount spent (debits) and number of payments, optionally filtered by merchant "
                       "name (case-insensitive substring, e.g. 'swiggy'), category and month.",
        "parameters": {"type": "object", "properties": {
            "merchant": {"type": "string", "description": "Merchant name or part of it, or a person alias like Person_03."},
            "category": {"type": "string", "enum": list(CATEGORIES)},
            "month": MONTH,
        }},
    }},
    {"type": "function", "function": {
        "name": "top_merchants",
        "description": "Merchants (not people) ranked by total spend, with totals and payment counts.",
        "parameters": {"type": "object", "properties": {
            "n": {"type": "integer", "description": "How many to return (default 10).", "minimum": 1, "maximum": 30},
            "month": MONTH,
        }},
    }},
    {"type": "function", "function": {
        "name": "compare_months",
        "description": "Spend in month m1 vs month m2, overall and per category. change = m2 - m1.",
        "parameters": {"type": "object", "properties": {
            "m1": {"type": "string", "description": "Earlier month, YYYY-MM."},
            "m2": {"type": "string", "description": "Later month, YYYY-MM."},
        }, "required": ["m1", "m2"]},
    }},
    {"type": "function", "function": {
        "name": "list_transactions",
        "description": "Individual matching transactions, newest first. Use for 'show me', 'which', 'when' questions.",
        "parameters": {"type": "object", "properties": {
            "month": MONTH,
            "merchant": {"type": "string"},
            "category": {"type": "string", "enum": list(CATEGORIES)},
            "direction": {"type": "string", "enum": ["debit", "credit"]},
            "cp_type": {"type": "string", "enum": ["merchant", "person", "unknown"]},
            "min_amount": {"type": "number"},
            "max_amount": {"type": "number"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        }},
    }},
    {"type": "function", "function": {
        "name": "month_overview",
        "description": "Full analysis of one month: income, spend, savings rate, spend by category, recurring "
                       "payments and subscriptions, small payments under Rs 200, transfers to people, "
                       "weekday vs weekend, change vs previous month, unusual payments. Use for advice "
                       "questions like 'what can I cut' or 'how am I doing'.",
        "parameters": {"type": "object", "properties": {"month": MONTH}},
    }},
]


def _list_tx(df, limit=20, **filters):
    return ins.list_transactions(df, {k: v for k, v in filters.items() if v not in (None, "")}, limit=limit or 20)


TOOLS: dict[str, Callable[..., Any]] = {
    "spend_by": lambda df, merchant=None, category=None, month=None: ins.spend_by(df, merchant, category, month),
    "top_merchants": lambda df, n=10, month=None: ins.top_merchants(df, n=int(n or 10), month=month),
    "compare_months": lambda df, m1, m2: ins.compare_months(df, m1, m2),
    "list_transactions": _list_tx,
    "month_overview": lambda df, month=None: ins.compute_insights(df, month),
}


def run_tool(name: str, args: dict | str | None, df: pd.DataFrame) -> dict:
    """Run one tool; errors go back to the model as data so it can fix its call."""
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except json.JSONDecodeError as e:
            return {"error": f"arguments were not valid JSON: {e}"}
    args = {k: v for k, v in (args or {}).items() if v is not None}
    if name not in TOOLS:
        return {"error": f"unknown tool {name!r}; available: {list(TOOLS)}"}
    try:
        return {"result": TOOLS[name](df, **args)}
    except TypeError as e:
        return {"error": f"bad arguments for {name}: {e}"}
    except ValueError as e:
        return {"error": str(e)}


def txn_count(name: str, result: Any) -> int:
    """How many transactions a tool result was computed from (for the UI caption)."""
    if not isinstance(result, (dict, list)):
        return 0
    if name == "spend_by":
        return int(result.get("count", 0))
    if name == "top_merchants":
        return sum(int(r.get("count", 0)) for r in result)
    if name == "list_transactions":
        return len(result)
    if name == "compare_months":
        return 0
    if name == "month_overview":
        return int(result.get("summary", {}).get("txn_count", 0))
    return 0
