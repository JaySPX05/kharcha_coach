# Kharcha Coach

**Turn an Indian bank statement into a spending coach — without handing your bank data to a chatbot.**

Students and first-job earners make 150–300 small UPI payments a month. Statements show them as
`UPI/DR/412345678901/SWIGGY/YESB/swiggy@ybl/Payment`, so nobody reads them. SMS-reading budget apps
feel invasive, and generic chatbots invent numbers.

Kharcha Coach:

1. reads your statement (PDF, including password-protected, or CSV),
2. decodes every UPI narration into merchant, VPA and person-vs-merchant,
3. **redacts PII on your machine** before anything reaches a model,
4. categorises merchants with **NVIDIA Nemotron Nano**,
5. computes every number with pandas,
6. answers questions with **Nemotron Super**, which calls our pandas functions as tools,
7. writes a monthly coach report with **Nemotron Ultra** from aggregates only.

All models run on **Nebius Token Factory** (OpenAI-compatible API).

## Quick start

Windows PowerShell:

```powershell
git clone <repo-url> kharcha-coach
cd kharcha-coach
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env        # then put your NEBIUS_API_KEY in .env
pytest -q                          # data pipeline tests, no API key needed
streamlit run app/main.py
```

macOS / Linux:

```bash
git clone <repo-url> kharcha-coach && cd kharcha-coach
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env               # then put your NEBIUS_API_KEY in .env
pytest -q
streamlit run app/main.py
```

No statement handy? Use the **sample** button in the app, or the synthetic files in `data/sample/`
(regenerate with `python scripts/make_synthetic.py`).

## How the data flows

```
            ┌──────────── core/ — runs locally, no network, no model calls ───────────┐
 upload ──▶ │ parse_statement ──▶ decode_upi ──▶ redact ──┐                            │
            │  PDF/CSV, password,   merchant, VPA,  Person_NN aliases,                 │
            │  balance check        person/merchant  digits masked                     │
            └─────────────────────────────────────────────┼──────────────────────────┘
                                         PII stops here ┆ ▼
                               llm/categorize.py   Nemotron Nano  (unique merchants, cached)
                                                         │
                                                         ▼
                               core/insights.py    pandas — every number comes from here
                                  │                │                  │
                                  ▼                ▼                  ▼
                     llm/chat.py (Super,   llm/coach.py (Ultra,   app/ dashboard
                     tool calls → insights) aggregates only)
```

| Step | Module | What it does |
|---|---|---|
| Parse | `core/parsers/` | CSV and PDF (ruled tables, and unruled tables found from header positions). Decrypts with pikepdf. Indian numbers `1,23,456.78`, dates `14/09/26` / `14-Sep-2026`, Dr/Cr columns or signed amounts, multi-line narrations, header/footer and opening/closing-balance rows. Stable `txn_id` so re-uploads don't duplicate. |
| Check | `core/parsers/common.py` | Running balance must add up (previous ± amount). If rows were misread, the file is refused with a friendly message instead of producing wrong numbers. |
| Decode | `core/upi.py` | Regex per narration style → channel, counterparty, VPA, and merchant / person / unknown (known-merchant map, shop words, QR-style handles, 10-digit phone handles, human names). |
| Redact | `core/redact.py` | People → stable `Person_01…` aliases; runs of 10+ digits (phones, UPI refs, account numbers) → last 4 only. Merchant names stay readable. |
| Insights | `core/insights.py` | Monthly in/out and savings rate, spend by category, top merchants, recurring payments, small-ticket leakage (< ₹200), transfers to people, weekday vs weekend, month-over-month change, unusual payments (> 3× category median). Plus the query tools the chat model calls: `spend_by`, `top_merchants`, `compare_months`, `list_transactions`. |

## Privacy design

| | |
|---|---|
| **Never leaves your machine** | The statement file, account numbers, phone numbers, real names of people you pay, UPI reference numbers, your PDF password |
| **What the models see** | Redacted rows: date, amount, direction, channel, merchant names (`Swiggy`), aliases (`Person_03`), masked VPAs (`person_03@ybl`), narrations with every long number reduced to its last 4 digits (`UPI/DR/XXXXXXXX1301/SWIGGY/…`) |
| **What the models never do** | Arithmetic. Every rupee figure in the chat and the report comes from `core/insights.py`; the model can only quote tool results. |

`core/` has no network code and never imports `llm/` — the whole data pipeline and its tests run
with no API key. Tests assert that no 10-digit number and no person's name survives `redact()`.

## How we use NVIDIA Nemotron and Nebius Token Factory

Three Nemotron 3 models, each sized to its job, all called at runtime through Token Factory's
OpenAI-compatible API (`llm/client.py` is the only place that talks to it):

| Tier | Model (Token Factory ID) | Job | Why this size |
|---|---|---|---|
| Nano | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | Categorise unique merchants, 40 per call | High volume, short answers; cheapest tier ($0.06 / $0.24 per 1M tokens). Reasoning off. |
| Super | `nvidia/nemotron-3-super-120b-a12b` | Chat that calls our pandas helpers as tools | Needs dependable tool calling at chat speed. Reasoning off. |
| Ultra | `nvidia/Nemotron-3-Ultra-550b-a55b` | Monthly coach report | One call per month that needs real reasoning over many numbers ($1 / $3 per 1M). Reasoning on. |

**The model never does arithmetic.** Super gets five tools (`spend_by`, `top_merchants`,
`compare_months`, `list_transactions`, `month_overview`) that wrap `core/insights.py`. It decides
*which* calculation to run; pandas runs it; Super phrases the result. Ultra only receives the
`compute_insights()` dict. After every answer, `llm/verify.py` extracts each number the model wrote
and flags any that isn't in (or a simple sum/difference of) the computed results — the app shows a
warning if that ever happens.

**Categorising cheaply.** Rules handle people (with UPI remarks like "rent"), credits, ATM and ~100
known Indian merchants. Only the leftovers go to Nano, as unique merchant names, 40 per request,
with JSON validated against the fixed category list and one retry. Results are cached by normalised
merchant name, so a merchant is classified once, ever. User fixes in the dashboard override the cache.

**What each model sees** is shown in the app's *What the AI saw* tab, with calls, tokens and
estimated cost per statement in the footer.

| Measured on the sample statement (Oct 25, 2026) | Value |
|---|---|
| Categoriser accuracy, 100 hand-labelled merchants (rules + Nano) | 91% (rules 77/77, one Nano call, $0.00015) |
| …of which decided by Nano | 14/23 hardest leftovers (61%) |
| Avg latency per call: Nano / Super | 2.2 s (40-merchant batch) / 1.2 s (20 calls, 10 questions) |
| Ultra coach report latency | 14.7 s (one call, 8,033 tokens) |
| Cost: categorising a 3-month statement / one chat answer / one coach report | < $0.001 (rules handle all but 2 merchants) / ~$0.002 (2 Super calls) / $0.018 (≈ Rs 1.5) |
| Chat: right tool chosen on the 10 test questions (final run) | 10/10; invented figures flagged by the number check in 1/10 |

Hosting: Streamlit Community Cloud (see Deploy below); all model calls go to Token Factory at runtime.

## Deploy

Streamlit Community Cloud (free, ~5 minutes):
1. share.streamlit.io → **Create app** → repo `JaySPX05/kharcha_coach`, branch `main`, main file `app/main.py`.
2. **Advanced settings** → Python 3.11 → Secrets: `NEBIUS_API_KEY = "..."`.
3. Deploy, open the URL, press **Try sample**.

Any container host: `docker build -t kharcha-coach .` then run with `-e NEBIUS_API_KEY=... -p 8501:8501`.
The app reads the port from `$PORT`, so it also works on hosts that assign one.

## Supported statements

- **CSV** exports with a header row containing Date, Narration/Description/Particulars, and either
  Debit/Withdrawal + Credit/Deposit or Amount (+ Dr/Cr), plus Balance. Account details above the
  table are skipped.
- **Text PDFs**, ruled or unruled, with those headers. Password-protected PDFs are supported.
- **Narration styles** decoded: slash style (`UPI/DR/ref/NAME/BANK/vpa/note`, SBI-like) and hyphen
  style (`UPI-NAME-vpa-IFSC-ref-NOTE`, HDFC-like), plus NEFT, IMPS, ATM and card rows; any other
  narration containing a VPA falls back to VPA-only decoding.
- **Not supported:** scanned (image-only) PDFs and Excel files — you get a clear message saying so.

Tested on synthetic statements in both styles. Real-bank layouts vary; if yours is refused,
the CSV export from net banking usually works.

## Tests

```powershell
pytest -q                     # everything (~30 s; PDF parsing dominates)
pytest tests/test_upi.py -v   # narration decoder cases
```

Covers schema validation, parsers (round-trip PDF ⇄ CSV, unruled PDFs, passwords, bad files,
balance guard), 23 hand-written narrations, redaction (no PII survives), and insights checked
against a statement small enough to verify by hand.

## Repo layout

```
app/        Streamlit UI
core/       data pipeline — local only (schema, parsers, upi, redact, insights)
llm/        Nemotron calls via Nebius Token Factory
data/sample synthetic statements only — no real bank data, ever
scripts/    make_synthetic.py
tests/
decisions.md  every design decision and why
```

## License

MIT
