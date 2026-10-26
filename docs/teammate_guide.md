# Teammate guide — the LLM layer and app

What every file does, the idea behind it, and the commands to run. Windows PowerShell throughout.

## 0. Setup (once)

```powershell
cd C:\Users\Keerthana\kharcha_coach
.\.venv\Scripts\Activate.ps1          # prompt starts with (.venv)
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env                          # paste your key after NEBIUS_API_KEY=
pytest -q                             # expect: 174 passed (no key needed)
```

## 1. Talk to Token Factory — `llm/client.py`

**Idea.** Token Factory speaks the same API as OpenAI ("OpenAI-compatible"), so the official
`openai` package works if you point `base_url` at Token Factory and give it your Nebius key. Every
other file calls `chat("nano" | "super" | "ultra", messages)` and never builds its own client. That
one function picks the model, retries on 429/5xx, logs latency/tokens/cost, and turns Nemotron's
"thinking" on or off with `extra_body={"chat_template_kwargs": {"enable_thinking": False}}`.

```powershell
python scripts/list_models.py         # prints Nemotron IDs + OK / NOT FOUND for each tier
python scripts/smoke_test.py          # one tiny call per tier: latency, tokens, cost
```
If a tier says NOT FOUND, copy the exact ID the script printed into `.env`.

## 2. Categorise merchants — `llm/categorize.py`, `llm/categories.py`, `llm/prompts/categorize.txt`

**Idea.** 200 payments a month but only ~20–40 different merchants. Rules decide everything they
can (people, credits, ATM, ~100 known merchants, "rent" in a UPI remark). Only leftover **unique**
merchant names go to Nano, 40 per call, and the answer is cached so each merchant is classified once.

```powershell
python scripts/eval_categorize.py --rules-only   # offline: ~80% decided by rules, 0 rule mistakes
python scripts/eval_categorize.py                # with Nano: write the accuracy into README
```
**Precision vs accuracy here:** accuracy = share of all merchants labelled right. Precision for a
category = of the merchants we *called* Groceries, how many really were. Rules have high precision
(they only fire when sure); Nano's job is to raise recall on the rest.

## 3. Chat with tools — `llm/chat.py`, `llm/tools.py`, `llm/prompts/chat_system.txt`

**Idea.** We send the question plus descriptions of 8 functions. Super answers "call
`spend_by(merchant='swiggy', month='2026-09')`". We run pandas, send the result back, and Super
writes the sentence. It never sees the data, so it can't make numbers up — and `llm/verify.py`
double-checks every number in its reply against the tool results.

```powershell
python scripts/check_tool_calling.py   # must say "native tool calling works"
python scripts/chat_questions.py       # the 10 test questions incl. Hinglish
```
If tool calling doesn't work, add `CHAT_MODE=plan` to `.env` (2 calls per answer, no chaining).

## 4. Coach report — `llm/coach.py`, `llm/prompts/coach.txt`

**Idea.** Ultra is 15x Nano's price, so it gets one job: reason over the month's *totals*
(`compute_insights()`), never transactions. Output is JSON (summary, budgets, 3 actions, watch-outs),
validated with one retry; we fill "spent this month" next to each budget ourselves and flag any
rupee figure not traceable to the input.

## 5. The app — `app/main.py`, `app/pipeline.py`

```powershell
streamlit run app/main.py              # opens http://localhost:8501 ; press "Try sample"
```
Tabs: Dashboard (number cards with sparklines, "where every ₹100 went" bar, day-by-day calendar,
monthly bars, small-payment callout, recurring, top merchants, fix-a-category table), Ask, Coach report, What the AI saw. Footer: calls, tokens, cost for this statement.
Without a key the app still runs (rules-only categories; chat and coach show a message).

## 6. Deploy (Day 5)

Streamlit Community Cloud first (decided Oct 25, see decisions.md); the Dockerfile keeps a Nebius container deploy open:
1. share.streamlit.io → New app → repo `JaySPX05/kharcha_coach`, branch `main`, file `app/main.py`.
2. Advanced settings → Python 3.11 → Secrets: `NEBIUS_API_KEY = "..."` (plus MODEL_* if different).
3. Open the URL on your phone, press **Try sample**.

`Dockerfile` is ready for container hosts (port from `$PORT`, default 8501); pass the key as an env var.

## 7. Before every push

```powershell
git status          # .env, real PDFs/CSVs and data/cache must NOT be listed
pytest -q
```
