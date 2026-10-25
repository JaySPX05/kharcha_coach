"""Nemotron Ultra monthly coach report.

Ultra is the expensive model, so it gets one call per month and only the
insights dict (aggregates from core/insights.py), never transactions. That's
both cheaper (a few thousand tokens) and private (no row-level data).

After generation we:
  - validate the JSON shape (retry once if broken),
  - overwrite each budget's "last_month" with the real figure from insights,
  - flag every rupee number in the text that isn't in, or derivable from, the input.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.schema import CATEGORIES
from llm.client import chat
from llm.verify import unverified_numbers

PROMPT = Path(__file__).parent / "prompts" / "coach.txt"


def _parse(text: str) -> dict:
    start, end = (text or "").find("{"), (text or "").rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in output")
    return json.loads(text[start:end + 1])


def _validate(rep: dict) -> list[str]:
    errs = []
    if not isinstance(rep.get("summary"), str) or not rep["summary"].strip():
        errs.append("summary must be a non-empty string")
    b = rep.get("budgets")
    if not isinstance(b, list) or not b:
        errs.append("budgets must be a non-empty list")
    else:
        for x in b:
            if not isinstance(x, dict) or x.get("category") not in CATEGORIES:
                errs.append(f"budget category must be one of the fixed list, got {x!r}")
            elif not isinstance(x.get("budget"), (int, float)):
                errs.append(f"budget for {x.get('category')} must be a number")
    a = rep.get("actions")
    if not isinstance(a, list) or len(a) != 3:
        errs.append("actions must be a list of exactly 3")
    else:
        for x in a:
            if not isinstance(x, dict) or not x.get("title") or not isinstance(x.get("rupee_impact"), (int, float)):
                errs.append(f"each action needs title, detail and a numeric rupee_impact, got {x!r}")
    if not isinstance(rep.get("watch_outs"), list):
        errs.append("watch_outs must be a list of strings")
    return errs


def _slim(insights: dict) -> dict:
    """Drop fields Ultra doesn't need, to keep tokens down."""
    keep = {k: v for k, v in insights.items() if k not in ("months",)}
    keep["top_merchants"] = insights.get("top_merchants", [])[:10]
    return keep


def coach_report(insights: dict, goal: str | None = None) -> dict:
    """Returns {summary, budgets, actions, watch_outs, unverified, month}."""
    payload = _slim(insights)
    prompt = (PROMPT.read_text(encoding="utf-8")
              .replace("{{MONTH}}", insights.get("month", ""))
              .replace("{{GOAL}}", goal.strip() if goal and goal.strip() else "none given — help them spend less and save more")
              .replace("{{INSIGHTS}}", json.dumps(payload, ensure_ascii=False)))
    messages = [{"role": "user", "content": prompt}]

    rep, errs = None, ["no output"]
    for attempt in range(2):
        msg = chat("ultra", messages, temperature=0.3, max_tokens=12000, purpose="coach",
                   payload_preview=payload)
        try:
            rep = _parse(msg.content)
            errs = _validate(rep)
        except (ValueError, json.JSONDecodeError) as e:
            errs = [f"invalid JSON: {e}"]
        if not errs:
            break
        messages += [{"role": "assistant", "content": msg.content or ""},
                     {"role": "user", "content": "Fix these problems and return only the JSON: " + "; ".join(errs)}]
    if errs:
        raise ValueError("Coach report failed validation: " + "; ".join(errs))

    actual = {c["category"]: c["total"] for c in insights.get("by_category", [])}
    for b in rep["budgets"]:
        b["last_month"] = actual.get(b["category"], 0.0)  # ours, not the model's

    source = [payload, goal or ""]
    text_parts = [rep["summary"], *rep.get("watch_outs", [])]
    text_parts += [f"{a.get('title', '')} {a.get('detail', '')} {a['rupee_impact']}" for a in rep["actions"]]
    rep["unverified"] = unverified_numbers("\n".join(map(str, text_parts)), source)
    rep["month"] = insights.get("month")
    return rep
