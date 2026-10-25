"""Measure categoriser accuracy on the 100-row hand-labelled set.

Run (needs API key):     python scripts/eval_categorize.py
Rules only (offline):    python scripts/eval_categorize.py --rules-only

Prints overall accuracy, accuracy split by who decided (rule vs llm), per-category
precision/recall, and every mistake. Uses a throwaway cache so results are honest.
"""
import argparse
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

if "--thinking" in sys.argv:
    os.environ["CATEGORIZE_THINKING"] = "1"

from llm.categorize import categorize  # noqa: E402
from llm.client import usage_summary  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--rules-only", action="store_true", help="no model calls; unmatched rows count as wrong")
ap.add_argument("--thinking", action="store_true", help="let Nano reason before answering")
args = ap.parse_args()

gold = pd.read_csv(ROOT / "data" / "eval" / "labelled_merchants.csv").fillna({"vpa": ""})
gold["vpa"] = gold["vpa"].replace("", None)

with tempfile.TemporaryDirectory() as tmp:
    out = categorize(gold, use_llm=not args.rules_only, cache_path=Path(tmp) / "cache.json")

out["correct"] = out["category"] == out["label"]
n = len(out)
print(f"\nOverall accuracy: {out['correct'].sum()}/{n} = {out['correct'].mean():.1%}")
for src, g in out.groupby("category_source"):
    print(f"  decided by {src:5}: {g['correct'].sum()}/{len(g)} = {g['correct'].mean():.1%}")

print("\nPer category (precision = of rows we called X, how many were X; recall = of true X, how many we found):")
for cat in sorted(set(out["label"]) | set(out["category"].dropna())):
    pred = out["category"] == cat
    true = out["label"] == cat
    tp = (pred & true).sum()
    p = tp / pred.sum() if pred.sum() else float("nan")
    r = tp / true.sum() if true.sum() else float("nan")
    print(f"  {cat:22} precision {p:5.0%}  recall {r:5.0%}  (n={true.sum()})")

wrong = out[~out["correct"]]
if len(wrong):
    print(f"\nMistakes ({len(wrong)}):")
    for _, r in wrong.iterrows():
        print(f"  {r['counterparty']:32} gold={r['label']:20} got={r['category']} [{r['category_source']}]")
    print("\nMost common confusions:", Counter(zip(wrong["label"], wrong["category"])).most_common(5))

if not args.rules_only:
    print("\nUsage:", usage_summary())
