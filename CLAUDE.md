# CLAUDE.md — Kharcha Coach

Read this whole file before doing anything in this repo. It tells you what we are building, how it fits together, what I (Jay) own, and how I want you to work with me.

---

## 1. What we are building

**Kharcha Coach** turns an Indian bank statement (PDF or CSV) into a spending coach:

1. Upload a statement (password-protected PDFs too).
2. Decode every UPI narration into merchant, VPA and person-vs-merchant.
3. Redact PII locally before anything reaches a model.
4. Categorise merchants with **NVIDIA Nemotron Nano**.
5. Compute all numbers with pandas.
6. Answer questions with **Nemotron Super** using tool calls into our pandas functions.
7. Write a monthly coach report with **Nemotron Ultra**.

All models are called through **Nebius Token Factory** (OpenAI-compatible API, `base_url = https://api.tokenfactory.nebius.com/v1/`).

- **Hackathon:** NVIDIA x Nebius, **Best Apps and Agents** track
- **Deadline:** Oct 30, 2026 (confirm exact time + timezone on Devpost)
- **Audience:** Indian students and first-job earners making 150–300 small UPI payments a month
- **Team:** Jay (data pipeline, this file's owner) + teammate (LLM layer + Streamlit app)

### The problem we solve
Statements show UPI payments as unreadable narrations like
`UPI/DR/412345678901/SWIGGY/YESB/swiggy@ybl/Payment`. Nobody reads them. SMS-reading budget apps feel invasive, and generic chatbots invent numbers. We decode, redact, and only let models talk about numbers pandas computed.

---

## 2. Architecture

```
            ┌──────────── core/ (Jay) — local, NO model calls ────────────┐
upload ──▶  parse_statement ──▶ decode_upi ──▶ redact ──┐  ┆ PII stops here
            └───────────────────────────────────────────┘  ┆
                                                           ▼
                                  llm/categorize.py  (Nemotron Nano, cached)
                                                           │
                                                           ▼
                                  core/insights.py   (pandas, all the maths)
                                     │            │                │
                                     ▼            ▼                ▼
                     llm/chat.py (Super +   llm/coach.py     app/ dashboard
                     tool calls → insights)  (Ultra, aggregates only)
                                     └────────────┴──── app/ (Streamlit) ◀┘
```

### Model routing (teammate owns this, but know it)

| Tier | Model ID (verify with `GET /v1/models`) | Job |
|---|---|---|
| Nano | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | Categorise unique merchants in batches |
| Super | `nvidia/nemotron-3-super-120b-a12b` | Chat that calls insight helper functions |
| Ultra | `nvidia/Nemotron-3-Ultra-550b-a55b` | Monthly coach report from aggregates |

Model IDs live in `.env` as `MODEL_NANO`, `MODEL_SUPER`, `MODEL_ULTRA`. Never hardcode them.

---

## 3. Repo layout and ownership

```
kharcha-coach/
├── app/                 # TEAMMATE — Streamlit UI
├── core/                # JAY — data pipeline (no LLM calls, ever)
│   ├── schema.py        # Transaction columns + validate()
│   ├── parsers/         # one file per bank format + csv
│   ├── upi.py           # narration decoder
│   ├── redact.py        # PII masking
│   └── insights.py      # all the maths + query helpers
├── llm/                 # TEAMMATE — everything that calls Token Factory
├── data/sample/         # synthetic statements ONLY
├── scripts/make_synthetic.py   # JAY
├── tests/               # both; Jay owns tests for core/
├── decisions.md         # both — every decision + why
├── README.md            # both
├── LICENSE              # MIT
├── .env.example
└── requirements.txt
```

**Do not edit `app/` or `llm/` while working on Jay's tasks** unless I explicitly ask. If something there blocks me, tell me and suggest a message for my teammate instead.

---

## 4. The shared contract (do not change without telling me)

### Transaction schema — `core/schema.py`

| Column | Type | Example | Filled by |
|---|---|---|---|
| `txn_id` | str | stable hash of date+amount+narration | Jay |
| `date` | date | 2026-09-14 | Jay |
| `narration` | str | `UPI/DR/4123…/SWIGGY/YESB/swiggy@ybl/Pay` | Jay |
| `amount` | float, always positive | 349.0 | Jay |
| `direction` | `debit` \| `credit` | debit | Jay |
| `balance` | float \| None | 12450.5 | Jay |
| `channel` | `UPI` \| `NEFT` \| `IMPS` \| `CARD` \| `ATM` \| `OTHER` | UPI | Jay |
| `counterparty` | str (alias for people) | Swiggy / `Person_07` | Jay |
| `vpa` | str \| None (phone digits masked) | swiggy@ybl | Jay |
| `cp_type` | `merchant` \| `person` \| `unknown` | merchant | Jay |
| `category` | str \| None | Food delivery | Teammate |
| `category_source` | `rule` \| `llm` \| `cache` \| `user` | llm | Teammate |

**Fixed categories:** Food delivery, Groceries, Eating out, Transport, Fuel, Shopping, Subscriptions, Bills & recharge, Rent, Education, Health, Entertainment, Travel, Transfers to people, Cash withdrawal, Investments, Income, Other.

### Function signatures

```python
# Jay — core/
parse_statement(file_bytes: bytes, filename: str, password: str | None = None) -> pd.DataFrame
decode_upi(df: pd.DataFrame) -> pd.DataFrame        # fills channel, counterparty, vpa, cp_type
redact(df: pd.DataFrame) -> pd.DataFrame            # masks PII
compute_insights(df: pd.DataFrame, month: str | None = None) -> dict   # JSON-safe

# Jay — query helpers in core/insights.py (teammate wraps these as model tools)
spend_by(df, merchant=None, category=None, month=None) -> dict
top_merchants(df, n=10, month=None) -> list[dict]
compare_months(df, m1: str, m2: str) -> dict
list_transactions(df, filters: dict, limit: int = 20) -> list[dict]

# Teammate — llm/  (for reference only)
categorize(df) -> df
answer(question, df, history) -> dict      # {text, tool_calls, numbers_used}
coach_report(insights, goal) -> dict       # {summary, budgets, actions, watch_outs}
```

Month strings are `"YYYY-MM"`. All returned dicts must be JSON-serialisable (no numpy types, no Timestamps — convert to float/int/str).

---

## 5. Non-negotiable rules

1. **`core/` never imports from `llm/`** and never makes a network call. The whole pipeline must run with zero API keys.
2. **Models never do arithmetic.** Every number shown or said comes from `core/insights.py`.
3. **Models only see redacted data.** No account numbers, phone numbers, real person names or UPI reference numbers ever leave `redact()`.
4. **No real bank data in git, ever.** Real statements stay on my laptop outside the repo. `data/sample/` is synthetic only. `.gitignore` blocks `.env`, `*.pdf`, `*.csv` everywhere except `data/sample/`. Before any commit, check `git status` for stray statements.
5. **No secrets in code.** Keys come from `.env` via `python-dotenv`.
6. Python 3.11, pandas, pdfplumber, pikepdf, pytest. Type hints on public functions. Small pure functions, easy to test.

---

## 6. How to work with me (Jay)

- **Go step by step.** One step at a time; wait for me to confirm it works before moving on.
- **Teach first, then code.** Before writing code, explain the concept in plain words (what it is, why we need it, what can go wrong). Then write the code and walk me through the non-obvious lines.
- **I use Windows PowerShell.** Give PowerShell commands only (e.g. `.\.venv\Scripts\Activate.ps1`, `$env:VAR="x"`, `Remove-Item`), never bash-only syntax.
- **After each step:** give the exact command to run and what output I should expect.
- **End of every session:** append entries to `decisions.md` under today's heading in this format:
  `**Decision** · Chosen · Alternatives considered · Why`
- When I paste sample rows from my real statement, they will already be redacted. Do not ask for full files.
- If a request conflicts with a rule in section 5, stop and tell me.

---

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

---

## 8. Useful commands (PowerShell)

```powershell
# setup
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# synthetic data
python scripts/make_synthetic.py

# tests
pytest -q
pytest tests/test_upi.py -v

# run the app (once teammate's app/ exists)
streamlit run app/main.py

# git — feature branch per day, PR into main
git checkout -b jay/day1-schema
git add .
git status        # check for real statements before committing!
git commit -m "core: schema + synthetic generator"
git push -u origin jay/day1-schema
```

---

## 9. What "good" looks like for judges

| Criterion | What my half contributes |
|---|---|
| Technological implementation | Clean, tested pipeline; models never do maths; correct handling of real Indian statement formats |
| Design | Fast, reliable upload with friendly errors |
| Potential impact | Real UPI narrations decoded correctly; insights that name specific rupee amounts |
| Quality of the idea | Local PII redaction + UPI decoding — specific to India and non-obvious |

Full plan, teammate's tasks and submission checklist: the team's "UPI Statement Coach — Build Plan & Prompts" doc.
