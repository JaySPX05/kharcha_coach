"""Nemotron Super chat with tool calling.

The loop:
  1. send question + tool schemas
  2. model replies with tool_calls (which helper, which args) -> we run pandas
  3. send results back as role="tool" messages -> repeat (max 4 rounds)
  4. model replies with plain text -> that's the answer
The model never sees the dataframe, only tool results, so it has nothing to
invent numbers from. llm/verify.py then flags any number not in those results.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

import pandas as pd

from llm.client import chat
from llm.tools import TOOL_SCHEMAS, run_tool, txn_count
from llm.verify import unverified_numbers

MAX_ROUNDS = 4
PROMPT = Path(__file__).parent / "prompts" / "chat_system.txt"
# "tools" = native function calling; "plan" = fallback where the model writes a JSON plan.
MODE = os.getenv("CHAT_MODE", "tools")

_TOOL_TAG = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


def _system_prompt(df: pd.DataFrame) -> str:
    months = sorted(pd.to_datetime(df["date"]).dt.strftime("%Y-%m").unique())
    latest = months[-1] if months else "unknown"
    return (PROMPT.read_text(encoding="utf-8")
            .replace("{{MONTHS}}", ", ".join(months))
            .replace("{{LATEST}}", latest)
            .replace("{{YEAR}}", latest[:4]))


_HINGLISH = re.compile(r"\b(kitna|kitne|kitni|kya|kyu|kyun|mera|meri|mere|maine|mujhe|hai|hain|tha|kaha|kahan|"
                       r"kharch|kharcha|paisa|paise|bheja|bheje|doston|dost|kaise|kab|kaun|bata|batao|zyada|kam)\b", re.I)


def is_hinglish(text: str) -> bool:
    """Two or more common Hindi words in Roman script -> treat as Hinglish."""
    return len(_HINGLISH.findall(text or "")) >= 2


def _language_note(question: str) -> dict:
    lang = "Hinglish (Roman-script Hindi mixed with English)" if is_hinglish(question) else "English"
    return {"role": "system", "content": f"Answer this question in {lang}."}


def _calls_from_text(content: str) -> list[dict]:
    """Some servers return Nemotron's raw <tool_call>{...}</tool_call> text instead of
    parsed tool_calls. Recover them so the loop still works."""
    calls = []
    for raw in _TOOL_TAG.findall(content or ""):
        try:
            obj = json.loads(raw)
            calls.append({"id": f"call_{uuid.uuid4().hex[:8]}", "name": obj["name"],
                          "arguments": json.dumps(obj.get("arguments", {}))})
        except (json.JSONDecodeError, KeyError):
            continue
    return calls


def _args(raw):
    """Tool arguments as a dict for the trace; broken JSON stays a string (run_tool already told the model)."""
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return raw


def _result(text: str, trace: list[dict], mode: str, question: str = "") -> dict:
    results = [t["result"] for t in trace if "result" in t]
    return {
        "text": text.strip(),
        # each call carries its own result (or error), so the UI never pairs a call with the wrong one
        "tool_calls": [{"name": t["name"], "arguments": t["arguments"],
                        "result": t["result"] if "result" in t else {"error": t.get("error")}} for t in trace],
        "numbers_used": results,
        "txn_count": sum(txn_count(t["name"], t.get("result")) for t in trace),
        # the user's own numbers ("save 3000") count as a source too
        "unverified": unverified_numbers(text, [results, question]),
        "mode": mode,
    }


def answer(question: str, df: pd.DataFrame, history: list | None = None) -> dict:
    """Answer a question about the statement.

    history: earlier turns as [{"role": "user"|"assistant", "content": str}, ...].
    Returns {text, tool_calls, numbers_used, txn_count, unverified, mode}.
    """
    if MODE == "plan":
        return answer_with_plan(question, df, history)

    messages = [{"role": "system", "content": _system_prompt(df)}]
    messages += [{"role": h["role"], "content": h["content"]} for h in (history or [])[-6:]]
    messages.append(_language_note(question))
    messages.append({"role": "user", "content": question})
    trace: list[dict] = []

    for _ in range(MAX_ROUNDS):
        msg = chat("super", messages, tools=TOOL_SCHEMAS, tool_choice="auto", temperature=0.2,
                   max_tokens=1200, purpose="chat", payload_preview={"question": question})
        calls = [{"id": c.id, "name": c.function.name, "arguments": c.function.arguments or "{}"}
                 for c in (msg.tool_calls or [])] or _calls_from_text(msg.content)
        if not calls:
            return _result(msg.content or "", trace, "tools", question)

        messages.append({"role": "assistant", "content": _TOOL_TAG.sub("", msg.content or "") or None,
                         "tool_calls": [{"id": c["id"], "type": "function",
                                         "function": {"name": c["name"], "arguments": c["arguments"]}}
                                        for c in calls]})
        for c in calls:
            out = run_tool(c["name"], c["arguments"], df)
            trace.append({"name": c["name"], "arguments": _args(c["arguments"]), **out})
            messages.append({"role": "tool", "tool_call_id": c["id"],
                             "content": json.dumps(out, ensure_ascii=False)})

    # out of rounds: ask for a final answer with no more tools
    messages.append({"role": "user", "content": "Answer now using only the tool results above."})
    msg = chat("super", messages, temperature=0.2, max_tokens=800, purpose="chat-final")
    return _result(msg.content or "", trace, "tools", question)


# ------------------------------------------------------------- fallback mode
_PLAN_PROMPT = """Decide which data functions to call to answer the user's question.
Functions (JSON schemas): {schemas}
Return ONLY JSON: {{"calls": [{{"name": "...", "arguments": {{...}}}}]}} with at most 3 calls."""


def answer_with_plan(question: str, df: pd.DataFrame, history: list | None = None) -> dict:
    """Fallback if native tool calling is unavailable: (1) model writes a JSON plan of
    helper calls, (2) we run them, (3) model writes the answer from the results.
    Trade-off: always 2 model calls, and no chance to call a follow-up tool after
    seeing a result."""
    schemas = json.dumps([t["function"] for t in TOOL_SCHEMAS])
    plan_msg = chat("super", [{"role": "system", "content": _system_prompt(df)},
                              {"role": "system", "content": _PLAN_PROMPT.format(schemas=schemas)},
                              {"role": "user", "content": question}],
                    temperature=0, max_tokens=600, purpose="chat-plan")
    text = plan_msg.content or ""
    try:
        plan = json.loads(text[text.find("{"): text.rfind("}") + 1])
        calls = plan.get("calls", [])[:3]
    except (json.JSONDecodeError, AttributeError):
        calls = [{"name": "month_overview", "arguments": {}}]

    trace = []
    for c in calls:
        out = run_tool(c.get("name", ""), c.get("arguments", {}), df)
        trace.append({"name": c.get("name"), "arguments": c.get("arguments", {}), **out})

    messages = [{"role": "system", "content": _system_prompt(df)}]
    messages += [{"role": h["role"], "content": h["content"]} for h in (history or [])[-6:]]
    messages.append({"role": "user", "content": f"{question}\n\nData from our tools:\n"
                                                f"{json.dumps(trace, ensure_ascii=False)}"})
    msg = chat("super", messages, temperature=0.2, max_tokens=800, purpose="chat")
    return _result(msg.content or "", trace, "plan", question)
