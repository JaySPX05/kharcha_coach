# Kharcha Coach — plan (moved from CLAUDE.md)

## 7. My tasks (Jay) — day by day

Hard checkpoint: **end of Day 4 (Tue Oct 27) — upload → report works end to end on the synthetic statement.**

### Day 1 · Sat Oct 24 — Repo foundation + synthetic data
- [ ] Repo skeleton per section 3, venv, `requirements.txt`, `.gitignore`, MIT `LICENSE`, `.env.example` (NEBIUS_API_KEY, MODEL_NANO, MODEL_SUPER, MODEL_ULTRA)
- [ ] `core/schema.py`: `COLUMNS`, allowed values, `CATEGORIES`, `validate(df)` with clear error messages
- [ ] `scripts/make_synthetic.py`: 3 months (Jul–Sep 2026) for a Bengaluru student on an allowance, fixed seed
  - ~200 UPI payments/month: Swiggy, Zomato, Zepto, Blinkit, Rapido, Namma Metro, chai shops, canteen, Amazon, Myntra, Spotify, Netflix, mobile recharge, rent
  - P2P transfers to friends (phone-number VPAs and name VPAs), a few NEFT/IMPS, 1–2 ATM withdrawals, monthly allowance credits
  - Realistic Indian UPI narrations in **2 different bank styles**
  - Outputs `data/sample/statement.csv` and `data/sample/statement.pdf`
- [ ] `tests/test_schema.py`, pytest runs green
- **Done when:** teammate can `pd.read_csv("data/sample/statement.csv")` and it passes `validate()` (category columns empty)

### Day 2 · Sun Oct 25 — Parsers
- [ ] Teach: pdfplumber table extraction, text vs scanned PDFs, password-protected PDFs with pikepdf
- [ ] `core/parsers/`: CSV parser, PDF parser for our synthetic format, one real bank format (from my redacted sample rows)
- [ ] Handle: multi-line narrations, Dr/Cr columns vs signed amount, Indian number format `1,23,456.78`, dates `14/09/26` and `14-Sep-2026`, header/footer rows, opening/closing balance rows
- [ ] Stable `txn_id` hash so re-uploads don't duplicate
- [ ] Tests with tiny fixture files
- **Done when:** my real statement parses locally (not committed) and the synthetic PDF round-trips to the same rows as the CSV

### Day 3 · Mon Oct 26 — UPI decoder + redaction
- [ ] Teach: VPA format `handle@psp`, PSP suffixes (`@ybl`, `@okhdfcbank`, `@paytm`, `@axl`…), UPI ref numbers, merchant vs personal VPAs
- [ ] `core/upi.py` `decode_upi`: regex per narration style, known-merchant map, person-vs-merchant heuristics (10-digit VPA, human name, no merchant keyword). Unclear → `unknown`. Explain each regex.
- [ ] `core/redact.py` `redact`: account numbers → last 4, mask 10-digit phones in VPAs, stable aliases `Person_01…` per person, strip UPI refs. Merchant names stay readable.
- [ ] Tests: ≥ 15 narration examples across both styles; a test proving no 10-digit number survives `redact()`
- **Done when:** synthetic statement → parse → decode → redact gives zero `unknown` channels and no PII in any column

### Day 4 · Tue Oct 27 — Insights engine + integration
- [ ] Teach: groupby, monthly resampling, detecting recurring payments
- [ ] `core/insights.py` `compute_insights`: monthly in/out, spend by category, top 10 merchants, savings rate, recurring/subscriptions (same merchant, similar amount, ~monthly), small-ticket leakage (< Rs 200 summed by category), transfers to people (count, total, top aliases), late-night spend (only if timestamps exist), weekend vs weekday, month-over-month change by category, unusual transactions (> 3× category median)
- [ ] Query helpers: `spend_by`, `top_merchants`, `compare_months`, `list_transactions`
- [ ] Tests with hand-checkable expected numbers on synthetic data
- [ ] Merge with teammate: replace their `core/insights_stub.py` with the real module, run full pipeline
- **Done when:** ✅ end-to-end demo works in the app

### Day 5 · Wed Oct 28 — Hardening
- [ ] Second real bank format parser
- [ ] Run on my real statements locally; list rows that failed or decoded as `unknown`; fix top causes
- [ ] Friendly errors: wrong password, scanned PDF, unsupported bank, empty file
- [ ] Full test suite green; pipeline < 2 s on a 3-month statement
- **Done when:** public URL (teammate deploys) works with the sample button and my real PDF locally

### Day 6 · Thu Oct 29 — README + video script
- [ ] README: what it does, quick start (PowerShell + bash), data pipeline with ASCII diagram, privacy design (what's redacted, what the model sees, what it never sees), supported banks, running tests
- [ ] Clean final `decisions.md`, grouped by area
- [ ] Demo video script < 2:45 — problem (15 s), upload sample, dashboard, 2 chat questions with exact numbers, coach report, "What the AI saw" panel, close on which Nemotron model does what and why. Mark on-screen action per line.

### Day 7 · Fri Oct 30 — Submit
- [ ] Fresh-clone install test on a clean folder
- [ ] Scan repo history for real data: `git log -p | Select-String -Pattern '\d{10}'` and any `.pdf` outside `data/sample/`
- [ ] Submit on Devpost with teammate

## What "good" looks like for judges

| Criterion | What my half contributes |
|---|---|
| Technological implementation | Clean, tested pipeline; models never do maths; correct handling of real Indian statement formats |
| Design | Fast, reliable upload with friendly errors |
| Potential impact | Real UPI narrations decoded correctly; insights that name specific rupee amounts |
| Quality of the idea | Local PII redaction + UPI decoding — specific to India and non-obvious |

Full plan, teammate's tasks and submission checklist: the team's "UPI Statement Coach — Build Plan & Prompts" doc.
