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
