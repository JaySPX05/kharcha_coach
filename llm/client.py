"""One place that talks to Nebius Token Factory.

Token Factory is OpenAI-compatible: same request/response shape as OpenAI's
Chat Completions API, just a different base_url and key. So we use the official
`openai` SDK and point it at Token Factory.

Everything else in llm/ calls `chat(tier, messages, ...)` and never builds its
own client. That gives us one spot for model routing, retries, timeouts,
reasoning on/off, token logging and cost.
"""
from __future__ import annotations

import os
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # dotenv is optional at runtime (e.g. platform secrets)
    pass

BASE_URL = os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")

# Defaults match Token Factory's published list (Oct 2026). Override in .env with
# whatever `python scripts/list_models.py` prints for your account.
MODELS = {
    "nano": os.getenv("MODEL_NANO", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"),
    "super": os.getenv("MODEL_SUPER", "nvidia/nemotron-3-super-120b-a12b"),
    "ultra": os.getenv("MODEL_ULTRA", "nvidia/Nemotron-3-Ultra-550b-a55b"),
}

# USD per 1M tokens (input, output), from Token Factory pricing, Oct 2026.
PRICES = {
    "nano": (0.06, 0.24),
    "super": (0.30, 0.90),
    "ultra": (1.00, 3.00),
}

# Reasoning ("thinking") default per tier. Nemotron 3 thinks by default; we turn
# it off where it only adds latency/tokens. Toggled with
# extra_body={"chat_template_kwargs": {"enable_thinking": bool}}.
THINKING = {"nano": False, "super": False, "ultra": True}

TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "90"))
MAX_RETRIES = 4
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 520, 522, 524, 529}  # 529 = "System is overloaded"

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


@dataclass
class CallLog:
    tier: str
    model: str
    purpose: str
    latency_s: float
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    ok: bool = True
    error: str | None = None
    payload_preview: Any = field(default=None, repr=False)


# Log of model calls. Scripts and tests use the process-wide CALL_LOG. The app gives each
# visitor's request its own list via `collect_calls()`, so concurrent visitors (threads in one
# Streamlit process) never see each other's calls and nothing grows for the life of the server.
CALL_LOG: list[CallLog] = []
_current_log: ContextVar[list[CallLog] | None] = ContextVar("current_log", default=None)


def _log(entry: CallLog) -> None:
    target = _current_log.get()
    (CALL_LOG if target is None else target).append(entry)


def collect_calls(fn, *args, **kwargs) -> tuple[Any, list[CallLog]]:
    """Run fn and return (its result, the model calls it made). On failure the calls made
    so far are attached to the exception as `.calls`."""
    calls: list[CallLog] = []
    token = _current_log.set(calls)
    try:
        return fn(*args, **kwargs), calls
    except Exception as e:
        e.calls = calls
        raise
    finally:
        _current_log.reset(token)


def reset_log() -> None:
    CALL_LOG.clear()


def usage_summary(log: list[CallLog] | None = None) -> dict:
    log = CALL_LOG if log is None else log
    out = {"calls": len(log), "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0, "by_tier": {}}
    for c in log:
        out["prompt_tokens"] += c.prompt_tokens
        out["completion_tokens"] += c.completion_tokens
        out["cost_usd"] += c.cost_usd
        t = out["by_tier"].setdefault(
            c.tier, {"calls": 0, "tokens": 0, "cost_usd": 0.0, "latency_s": []}
        )
        t["calls"] += 1
        t["tokens"] += c.prompt_tokens + c.completion_tokens
        t["cost_usd"] += c.cost_usd
        t["latency_s"].append(c.latency_s)
    for t in out["by_tier"].values():
        lat = t.pop("latency_s")
        t["avg_latency_s"] = round(sum(lat) / len(lat), 2) if lat else 0.0
    return out


def cost_usd(tier: str, prompt_tokens: int, completion_tokens: int) -> float:
    pin, pout = PRICES[tier]
    return (prompt_tokens * pin + completion_tokens * pout) / 1_000_000


def strip_reasoning(text: str | None) -> str:
    """Remove any <think>...</think> block and a dangling '</think>' prefix."""
    if not text:
        return ""
    text = _THINK_RE.sub("", text)
    if "</think>" in text:  # opening tag sometimes lives in the template, not the output
        text = text.split("</think>", 1)[1]
    return text.strip()


_client = None


def get_client():
    """Lazily build one OpenAI client pointed at Token Factory."""
    global _client
    if _client is None:
        from openai import OpenAI

        key = os.getenv("NEBIUS_API_KEY")
        if not key:
            raise RuntimeError(
                "NEBIUS_API_KEY is not set. Copy .env.example to .env and add your Token Factory key."
            )
        _client = OpenAI(base_url=BASE_URL, api_key=key, timeout=TIMEOUT_S, max_retries=0)
    return _client


def set_client(client) -> None:
    """Swap in a fake client (tests, offline demo)."""
    global _client
    _client = client


def _status_of(err: Exception) -> int | None:
    return getattr(err, "status_code", None) or getattr(getattr(err, "response", None), "status_code", None)


def chat(
    tier: str,
    messages: list[dict],
    *,
    purpose: str = "",
    thinking: bool | None = None,
    payload_preview: Any = None,
    **kwargs,
):
    """Call a Nemotron tier. Returns the raw ChatCompletion message object.

    The returned message's `.content` already has reasoning stripped.
    kwargs pass through to chat.completions.create (tools, temperature,
    max_tokens, response_format, ...).
    """
    if tier not in MODELS:
        raise ValueError(f"tier must be one of {list(MODELS)}, got {tier!r}")
    model = MODELS[tier]
    think = THINKING[tier] if thinking is None else thinking

    extra_body = dict(kwargs.pop("extra_body", {}) or {})
    tmpl = dict(extra_body.get("chat_template_kwargs", {}) or {})
    tmpl.setdefault("enable_thinking", think)
    extra_body["chat_template_kwargs"] = tmpl

    client = get_client()
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        t0 = time.perf_counter()
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages, extra_body=extra_body, **kwargs
            )
            latency = time.perf_counter() - t0
            usage = getattr(resp, "usage", None)
            pt = getattr(usage, "prompt_tokens", 0) or 0
            ct = getattr(usage, "completion_tokens", 0) or 0
            log = CallLog(tier, model, purpose, round(latency, 3), pt, ct, cost_usd(tier, pt, ct),
                          payload_preview=payload_preview)
            _log(log)
            print(f"[llm] tier={tier} purpose={purpose} latency={latency:.2f}s "
                  f"tokens={pt}+{ct} cost=${log.cost_usd:.5f}")
            msg = resp.choices[0].message
            msg.content = strip_reasoning(msg.content)
            return msg
        except Exception as e:  # noqa: BLE001 — we classify below
            last_err = e
            status = _status_of(e)
            name = type(e).__name__
            retryable = status in RETRYABLE_STATUS or name in {"APITimeoutError", "APIConnectionError"}
            if not retryable or attempt == MAX_RETRIES:
                _log(CallLog(tier, model, purpose, round(time.perf_counter() - t0, 3),
                                        0, 0, 0.0, ok=False, error=f"{name}: {e}",
                                        payload_preview=payload_preview))
                raise
            wait = min(2 ** attempt + 0.25 * attempt, 10)
            print(f"[llm] tier={tier} retry {attempt + 1}/{MAX_RETRIES} after {name} ({status}); sleep {wait:.1f}s")
            time.sleep(wait)
    raise last_err  # pragma: no cover

