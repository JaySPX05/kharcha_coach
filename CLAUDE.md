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

Ownership: `core/`, `scripts/`, tests for `core/` → Jay. `app/`, `llm/` → teammate. `data/sample/` is synthetic only. `decisions.md` and `README.md` → both.

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

## 7. Plan and judging criteria

Day-by-day tasks and what judges look for: `docs/plan.md`. Hard checkpoint: end of Day 4 (Tue Oct 27), upload → report works end to end on the synthetic statement.

---

## 8. Useful commands (PowerShell)

```powershell
streamlit run app/main.py   # once teammate's app/ exists

# git — feature branch per day, PR into main
git checkout -b jay/day1-schema
git status        # check for real statements before committing!
```

---

