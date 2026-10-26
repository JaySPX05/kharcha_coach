"""Ask the 10 test questions against the sample statement and print answers + flags.

Run: python scripts/chat_questions.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.pipeline import run_pipeline  # noqa: E402
from llm.chat import answer  # noqa: E402
from llm.client import usage_summary  # noqa: E402

QUESTIONS = [
    "How much did I spend on Swiggy in September?",
    "kitna paisa doston ko bheja?",
    "What can I cut to save 3000 next month?",
    "Compare August and September",
    "What are my top 5 merchants this month?",
    "Which subscriptions am I paying for?",
    "How much did I spend on chai and snacks under 200 rupees?",
    "Show my biggest 3 payments in September",
    "Did my food delivery spending go up?",
    "Mera savings rate kya hai?",
]

df = run_pipeline((ROOT / "data/sample/statement.csv").read_bytes(), "statement.csv")
for q in QUESTIONS:
    r = answer(q, df, [])
    print(f"\nQ: {q}\nA: {r['text']}")
    print(f"   tools: {[c['name'] for c in r['tool_calls']]}  txns: {r['txn_count']}  "
          f"unverified: {r['unverified'] or 'none'}")
print("\n", usage_summary())
