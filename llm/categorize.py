"""Nemotron Nano merchant categoriser.

Why unique merchants, not transactions: a month has ~200 payments but only
~40 distinct merchants, and 60 Swiggy orders are all "Food delivery". Classify
each merchant once, broadcast the answer to every row, and remember it in a
cache so the next statement (or re-upload) costs nothing for known merchants.

Order of precedence for each row:
  1. deterministic rules      -> category_source = "rule"   (people, credits, ATM, keyword map)
  2. cache from earlier runs  -> "cache"
  3. Nano, batches of 40      -> "llm"
User fixes in the dashboard apply to that session only and never touch the cache.
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

import pandas as pd

from llm.categories import CATEGORIES, normalise_merchant, rule_category
from llm.client import chat

BATCH_SIZE = 40
# Nano thinks before answering when this is on: slower and more tokens, but better on
# unfamiliar merchant names. Measured with scripts/eval_categorize.py --thinking.
THINKING = os.getenv("CATEGORIZE_THINKING", "0").lower() in ("1", "true", "yes")
PROMPT_PATH = Path(__file__).parent / "prompts" / "categorize.txt"
CACHE_PATH = Path(os.getenv("CATEGORY_CACHE", Path(__file__).resolve().parents[1] / "data" / "cache" / "merchant_categories.json"))

_lock = threading.Lock()


# ---------------------------------------------------------------- cache
def load_cache(path: Path | None = None) -> dict:
    path = path or CACHE_PATH
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_cache(cache: dict, path: Path | None = None) -> None:
    path = Path(path or CACHE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------- model call
def _extract_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    return json.loads(text[start:end + 1])


def _build_prompt(merchants: list[str]) -> str:
    tmpl = PROMPT_PATH.read_text(encoding="utf-8")
    return (tmpl.replace("{{CATEGORIES}}", "\n".join(f"- {c}" for c in CATEGORIES))
                .replace("{{MERCHANTS}}", "\n".join(merchants)))


def classify_batch(merchants: list[str]) -> dict[str, str]:
    """Ask Nano for one batch. Validates every value; retries once on bad output.
    Returns {merchant_string: category}; anything unusable becomes 'Other'."""
    messages = [{"role": "user", "content": _build_prompt(merchants)}]
    result: dict[str, str] = {}
    for attempt in range(2):
        msg = chat("nano", messages, purpose="categorize", temperature=0,
                   max_tokens=12000 if THINKING else 3000, thinking=THINKING,
                   payload_preview={"merchants": merchants})
        try:
            raw = _extract_json(msg.content)
        except (ValueError, json.JSONDecodeError) as e:
            messages += [{"role": "assistant", "content": msg.content or ""},
                         {"role": "user", "content": f"That was not valid JSON ({e}). Return only the JSON object."}]
            continue
        # tolerate small key drift (case/whitespace) by matching on normalised name
        by_norm = {normalise_merchant(k): v for k, v in raw.items()}
        bad = []
        for m in merchants:
            v = raw.get(m, by_norm.get(normalise_merchant(m)))
            if v in CATEGORIES:
                result[m] = v
            else:
                bad.append(m)
        if not bad:
            return result
        merchants_left = bad
        messages = [{"role": "user", "content": _build_prompt(merchants_left)}]
        merchants = merchants_left
    for m in merchants:
        result.setdefault(m, "Other")
    return result


# A payment to a person is usually a friend, but the UPI remark (the note the payer
# typed, last segment of the narration) often says what it was for: "rent", "fees".
REMARK_RULES = [
    (re.compile(r"\b(rent|pg|hostel|room|flat|deposit)\b", re.I), "Rent"),
    (re.compile(r"\b(fees?|tuition|coaching|exam)\b", re.I), "Education"),
    (re.compile(r"\b(electricity|wifi|broadband|maid|cook)\b", re.I), "Bills & recharge"),
]


def _person_category(narration) -> str:
    remark = re.split(r"[/-]", narration)[-1] if isinstance(narration, str) else ""
    for rx, cat in REMARK_RULES:
        if rx.search(remark):
            return cat
    return "Transfers to people"


# ---------------------------------------------------------------- main entry
def _s(x) -> str:
    """NaN/None-safe string (pandas gives NaN for empty cells, and NaN is truthy)."""
    return x if isinstance(x, str) else ""


def _label(row) -> str:
    """The merchant string we show the model: name plus handle when it helps."""
    cp = _s(row.get("counterparty")).strip()
    vpa = _s(row.get("vpa"))
    if vpa and normalise_merchant(vpa.split("@")[0]) not in normalise_merchant(cp):
        return f"{cp} ({vpa})" if cp else vpa
    return cp or vpa or "UNKNOWN"


def categorize(df: pd.DataFrame, *, use_llm: bool = True, cache_path: Path | None = None) -> pd.DataFrame:
    """Fill `category` and `category_source`. Never sees raw narrations, only
    the (already redacted) counterparty and VPA columns."""
    df = df.copy()
    for col in ("category", "category_source"):
        if col not in df.columns:
            df[col] = None
    df["category"] = df["category"].astype(object)
    df["category_source"] = df["category_source"].astype(object)

    cache = load_cache(cache_path)
    pending: dict[str, list] = {}  # label -> row indexes waiting for the model

    for idx, row in df.iterrows():
        key = normalise_merchant(_s(row.get("counterparty")) or _s(row.get("vpa")))
        hit = cache.get(key)

        cat = None
        if row.get("direction") == "credit":
            cat = "Income"
        elif row.get("channel") == "ATM":
            cat = "Cash withdrawal"
        elif row.get("cp_type") == "person" or _s(row.get("counterparty")).startswith("Person_"):
            # aliases tell Nano nothing and differ per statement, so they never reach it or the cache
            cat = _person_category(row.get("narration"))
        else:
            cat = rule_category(row.get("counterparty"), row.get("vpa"))
        if cat:
            df.at[idx, "category"], df.at[idx, "category_source"] = cat, "rule"
            continue

        if hit:
            df.at[idx, "category"], df.at[idx, "category_source"] = hit["category"], "cache"
            continue

        pending.setdefault(_label(row), []).append(idx)

    if pending and use_llm:
        labels = list(pending)
        for i in range(0, len(labels), BATCH_SIZE):
            batch = labels[i:i + BATCH_SIZE]
            got = classify_batch(batch)
            for label, cat in got.items():
                for idx in pending.get(label, []):
                    df.at[idx, "category"], df.at[idx, "category_source"] = cat, "llm"
                first = pending[label][0]
                key = normalise_merchant(_s(df.at[first, "counterparty"]) or _s(df.at[first, "vpa"]) or label)
                cache[key] = {"category": cat, "source": "llm"}
        with _lock:
            disk = load_cache(cache_path)
            disk.update(cache)
            save_cache(disk, cache_path)
    elif pending:
        for idxs in pending.values():
            for idx in idxs:
                df.at[idx, "category"], df.at[idx, "category_source"] = "Other", "rule"

    return df

