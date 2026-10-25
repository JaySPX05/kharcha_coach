"""One tiny call to each Nemotron tier; prints latency, tokens and cost.

Run:  python scripts/smoke_test.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm.client import chat, usage_summary  # noqa: E402

for tier in ("nano", "super", "ultra"):
    try:
        msg = chat(tier, [{"role": "user", "content": "Reply with exactly: ok"}],
                   purpose="smoke", max_tokens=400, thinking=False)
        print(f"{tier:6} -> {msg.content!r}")
    except Exception as e:  # noqa: BLE001
        print(f"{tier:6} FAILED: {type(e).__name__}: {e}")

print(usage_summary())
