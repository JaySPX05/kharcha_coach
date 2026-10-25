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
                       "name (case-insensitive substring, e.g. 'swiggy'), category and month. For money sent to "
                       "friends use category 'Transfers to people'.",
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
    {"type": "function", "function": {
        "name": "sum_transactions",
        "description": "Total, count and per-merchant / per-category totals for transactions matching filters, "
                       "including amount ranges. Money sent to friends = category 'Transfers to people'. Use for questions like 'how much on payments under Rs 200', "
                       "'how much on chai and snacks', 'total of payments above Rs 1000'.",
        "parameters": {"type": "object",
        "properties": {
            "month": MONTH,
            "merchant": {"type": "string", "description": "Merchant name or part of it, or a person alias."},
            "category": {"type": "string", "enum": list(CATEGORIES)},
            "direction": {"type": "string", "enum": ["debit", "credit"], "description": "Default debit (money spent)."},
            "min_amount": {"type": "number", "description": "Only payments of at least this many rupees."},
            "max_amount": {"type": "number", "description": "Only payments of at most this many rupees."},
        }},
    }},
    {"type": "function", "function": {
        "name": "largest_transactions",
        "description": "The biggest transactions by amount (largest first), with optional filters. "
                       "Use for 'biggest', 'largest', 'most expensive' questions.",
        "parameters": {"type": "object",
        "properties": {
            "month": MONTH,
            "merchant": {"type": "string", "description": "Merchant name or part of it, or a person alias."},
            "category": {"type": "string", "enum": list(CATEGORIES)},
            "direction": {"type": "string", "enum": ["debit", "credit"], "description": "Default debit (money spent)."},
            "min_amount": {"type": "number", "description": "Only payments of at least this many rupees."},
            "max_amount": {"type": "number", "description": "Only payments of at most this many rupees."},
            "n": {"type": "integer", "minimum": 1, "maximum": 20, "description": "How many (default 5)."},
        }},
    }},
    {"type": "function", "function": {
        "name": "recurring_payments",
        "description": "Recurring payments and subscriptions detected across months (same payee, similar amount, "
                       "about monthly): rent, recharges, streaming, etc. Use for 'subscriptions', 'fixed costs', "
                       "'what do I pay every month'.",
        "parameters": {"type": "object", "properties": {}},
    }},
]


def _list_tx(df, limit=20, **filters):
    return ins.list_transactions(df, {k: v for k, v in filters.items() if v not in (None, "")}, limit=limit or 20)


def _matching(df, direction="debit", **filters) -> pd.DataFrame:
    """All transactions matching the filters, as a DataFrame. Filtering is done by
    core/insights.list_transactions so the semantics match the other tools."""
    f = {k: v for k, v in {**filters, "direction": direction}.items() if v not in (None, "")}
    rows = ins.list_transactions(df, f, limit=len(df))
    return pd.DataFrame(rows, columns=["txn_id", "date", "counterparty", "amount", "direction", "category", "channel"])


def _sum_tx(df, **filters):
    m = _matching(df, **filters)
    by = lambda col, label: [  # noqa: E731
        {label: str(k), "total": round(float(v["amount"].sum()), 2), "count": int(len(v))}
        for k, v in sorted(m.groupby(col), key=lambda kv: -kv[1]["amount"].sum())][:10]
    return {"filters": {k: v for k, v in filters.items() if v is not None},
            "total": round(float(m["amount"].sum()), 2), "count": int(len(m)),
            "by_merchant": by("counterparty", "merchant"), "by_category": by("category", "category")}


def _largest(df, n=5, **filters):
    m = _matching(df, **filters).sort_values("amount", ascending=False, kind="stable").head(int(n or 5))
    return m.drop(columns=["txn_id"]).to_dict("records")


def _recurring(df):
    return ins.compute_insights(df)["recurring"]


TOOLS: dict[str, Callable[..., Any]] = {
    "spend_by": lambda df, merchant=None, category=None, month=None: ins.spend_by(df, merchant, category, month),
    "top_merchants": lambda df, n=10, month=None: ins.top_merchants(df, n=int(n or 10), month=month),
    "compare_months": lambda df, m1, m2: ins.compare_months(df, m1, m2),
    "list_transactions": _list_tx,
    "month_overview": lambda df, month=None: ins.compute_insights(df, month),
    "sum_transactions": _sum_tx,
    "largest_transactions": _largest,
    "recurring_payments": _recurring,
}


def _period(name: str, args: dict, df: pd.DataFrame) -> str:
    """Say which months a result covers, so the model can't label an all-months total as 'September'."""
    if name == "compare_months":
        return f"{args.get('m1')} vs {args.get('m2')}"
    if args.get("month"):
        return str(args["month"])
    if name == "month_overview":
        return "latest month (see 'month' in the result)"
    months = sorted(pd.to_datetime(df["date"]).dt.strftime("%Y-%m").unique())
    return f"ALL months combined ({months[0]} to {months[-1]}), not a single month" if months else "all months"


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
        return {"period": _period(name, args, df), "result": TOOLS[name](df, **args)}
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
    if name == "sum_transactions":
        return int(result.get("count", 0))
    if name == "largest_transactions":
        return len(result)
    if name == "month_overview":
        return int(result.get("summary", {}).get("txn_count", 0))
    return 0
