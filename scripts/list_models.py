"""Print every Nemotron model ID your Token Factory key can see.

Run:  python scripts/list_models.py
Then copy the exact IDs into .env as MODEL_NANO / MODEL_SUPER / MODEL_ULTRA.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm.client import get_client, MODELS  # noqa: E402

models = sorted(m.id for m in get_client().models.list())
nemo = [m for m in models if "nemotron" in m.lower()]
print(f"{len(models)} models visible, {len(nemo)} Nemotron:")
for m in nemo:
    print("  ", m)

print("\nConfigured tiers:")
for tier, mid in MODELS.items():
    print(f"  {tier:6} {mid:45} {'OK' if mid in models else 'NOT FOUND - fix .env'}")
