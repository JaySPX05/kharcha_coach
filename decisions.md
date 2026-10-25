# Decisions

Format: **Decision** · Chosen · Alternatives considered · Why

## 2026-10-24

- **Python version** · 3.11 via `py -3.11 -m venv .venv` · default `python` (3.14 on Jay's machine) · CLAUDE.md pins 3.11; 3.14 wheels for pdfplumber/pikepdf less certain
- **Real-data guard** · `.gitignore` blocks `*.pdf`, `*.csv`, `*.xls*` everywhere, re-allows only `data/sample/` · per-folder ignores · one rule covers stray statements dropped anywhere; `git add -f` still bypasses it, so `git status` before commits stays mandatory
- **`validate()` behaviour** · raises one `ValueError` listing every problem with up to 5 row indexes each · fail on first error; return a list of errors · real statements have many problems at once; one exception keeps callers simple
- **`txn_id`** · sha1 of `date|amount:.2f|direction|narration`, first 16 hex, in `core/schema.py` · row index; uuid · stable across re-uploads so no duplicates; UPI ref inside narration keeps it unique; shared so all parsers use it
- **PDF writer for synthetic data** · fpdf2 (`pdf.table`, fixed creation date) · reportlab; HTML-to-PDF · small pure-Python dependency, table API wraps narrations and repeats headers, byte-stable output
- **Two narration styles** · two files from the same seeded transactions: `statement.*` style A (SBI-like slashes, `dd/mm/yy`), `statement_b.*` style B (HDFC-like hyphens, `dd-Mon-yyyy`) · one file mixing styles per row · each file looks like a real single-bank statement; same transactions make cross-style decoder tests easy
- **Sample CSV content** · full schema with ground-truth decoded + redacted columns, categories empty · bank columns only · teammate can build against it today; becomes the expected output for parse→decode→redact on Day 3
- **Redacted person format** · `counterparty = Person_NN` by first appearance; `vpa = person_NN@<psp>`; ATM rows `cp_type = unknown`, counterparty `ATM` · masked phone `XXXXXX1234@ybl` · no digits and no names leave redaction, PSP kept for analysis; this is the target `redact()` must produce
- **Synthetic balances** · allowance Rs 30k, rent Rs 6k, skip any payment that would overdraw · let balance go negative · student accounts can't go negative; tuned so nothing is skipped and spend rises Jul→Sep for a coaching story
- **No real bank branding in samples** · "Synthetic Bank", fake `90000xxxxx` phones · real bank names/logos · avoids impersonating a real bank or person

## 2026-10-25 (Day 2: parsers + decoder + redaction)

- **Wrapped PDF narrations** · join wrapped lines with no space; `txn_id` ignores all whitespace · join with a space; use character x-positions to guess · a mid-word wrap joined with a space would split a VPA; ignoring whitespace in the id gives the PDF and the CSV of the same statement identical ids. Cost: names can come out glued ("PESCANTEEN"), handled below
- **One parser core for CSV and PDF** · both map header keywords to fields (`map_columns`), then share `add_rows` · one parser per bank · Debit/Credit vs Amount+Dr/Cr, Indian numbers, opening/closing rows and continuation rows get handled once; a new bank is usually just new header keywords
- **PDF tables** · pdfplumber `extract_tables()` on ruled tables; friendly error otherwise · text-position parsing now · our synthetic PDF is ruled; build text parsing once a real bank's layout needs it
- **Encrypted PDFs** · pikepdf decrypts in memory, then pdfplumber reads it · pdfplumber's own password support · pikepdf handles AES-256 and tells a wrong password apart from a damaged file
- **Duplicate rows** · identical day+amount+narration get `-2`, `-3` suffixes on the id · drop them · a student can genuinely pay ₹20 for chai twice; suffixes stay the same on re-upload
- **Person vs merchant** · known-merchant map → shop words in the name (6+ letter words also match glued names) → merchant-style handle (paytmqr, Q123…, gpay-, biz PSPs) → phone handle = person → 1–4 alphabetic words = person → otherwise unknown · send these rows to the LLM · keeps decoding local and deterministic; "unknown" stays honest
- **One display name per VPA** · rows sharing a VPA use the name variant with the most spaces · keep each row's own name · otherwise "Pes Canteen" and "Pescanteen" show up as two merchants
- **Redaction** · runs of 10+ digits → only the last 4 kept (phones, refs, accounts); person key = name with spaces removed; aliases also replace glued names in narrations · remove refs completely · one rule covers every number type; last 4 of a ref isn't PII. Unknown counterparties on UPI/NEFT/IMPS are aliased too, to stay safe

## 2026-10-26 (Day 3: insights engine)

- **Month buckets** · `dt.strftime("%Y-%m")` strings, then groupby · `resample("MS")` · matches the contract's `"YYYY-MM"` format and is JSON-safe without conversion
- **Spend / income definition** · spend = all debits (transfers, rent and ATM included), income = all credits; savings rate = (income − spend) / income in percent · leave out transfers and ATM · the student's money really leaves either way; categories already show where it went
- **Recurring detection** · same counterparty, amount within ±10% of its median, exactly one such payment per month, 20–40 days apart; merchants need 2+ months, people 3+, ATM never · fixed list of subscription brands; looking for periodicity in the dates · catches rent and unknown subscriptions; the per-person minimum stops two equal friend payments counting by chance
- **Unusual transactions** · amount > 3× the median of its category over all months, recurring payments excluded · z-score; per-month median · a median ignores outliers and works with few rows; rent is expected, not unusual
- **Weekday vs weekend** · totals plus per-day averages over the calendar days of the month · totals only · a month has ~22 weekdays and ~8 weekend days, so raw totals mislead
- **Late-night spend** · returns `{"available": false}` · guess from row order · statements give dates only; never invent numbers
- **Missing categories** · treated as "Other" inside insights · raise an error · insights work before the LLM categoriser is ready
- **Query helpers** · `merchant` filter is a case-insensitive substring; `list_transactions` rejects unknown filter keys · exact match; ignore unknown keys · the model will say "swiggy" or "lakshmi"; a loud error tells it to fix its tool call instead of silently returning everything

## 2026-10-27 (Day 4: hardening, docs)

- **Unruled PDFs** · column lines drawn at the header words' positions; a number column starts where its widest number starts (numbers are right-aligned) · pdfplumber's "text" strategy · the text strategy merged "Debit Credit" into one column on pages with few credits, and the parser then silently used the previous page's columns. Header positions are stable on every page
- **Balance guard** · every parser checks balance = previous ± amount (oldest-first or newest-first); more than max(2, 2% of rows) breaks → refuse with a friendly message · trust the parser · a misread column gives wrong numbers with no error; refusing is better than coaching on garbage. It also catches dropped rows
- **Page footers** · lines like "Page 3 of 23" / "computer generated" are never glued onto a narration · strip by fixed position · works for any bank, and text position varies
- **PDF speed** · accept ~4–5 s for a 23-page PDF (CSV 0.15 s; decode + redact + insights < 0.1 s) · rewrite on pypdfium2 · pdfminer needs ~2.5 s just to read the characters, so under 2 s isn't possible with pdfplumber; it runs once per upload behind a spinner
- **Demo numbers** · the video script uses only merchant-level figures (Swiggy ₹3,007 → ₹5,999) · category totals · merchant totals don't depend on the LLM categoriser, so they can't drift before recording

## 2026-10-25 (teammate: LLM layer + app)

- **One Token Factory client** · `llm/client.py` with `chat(tier, messages)`; model IDs from `.env` with published defaults · a client per module · one place for routing, retries (429/5xx/timeouts, exponential backoff, 3 tries), token + cost logging, and reasoning on/off
- **Reasoning per tier** · off for Nano and Super, on for Ultra, via `extra_body={"chat_template_kwargs": {"enable_thinking": ...}}`; any `<think>…</think>` text stripped from content · reasoning everywhere · Nemotron 3 thinks by default; for categorising and tool-routing it only adds latency and tokens. The coach report is the one job that benefits
- **Rules before Nano** · people, credits, ATM and ~100 keyword rules decide first; only leftovers go to Nano · send every merchant to Nano · on the sample statement rules cover all but 2 merchants, so Nano costs almost nothing. Rule order matters ("College Canteen" is Eating out, not Education)
- **Rent paid to a person** · read the UPI remark (last narration segment) for rent/pg/hostel/fee words · leave every person payment as "Transfers to people" · landlords are people; without this, rent shows up as the biggest "transfer" and the budget advice is wrong
- **Nano batching** · unique merchant names, 40 per call, JSON only, every value checked against the fixed list, one retry for bad JSON or invalid categories, then "Other" · one call per transaction · ~200 payments a month but ~20–40 merchants
- **Merchant cache** · JSON file keyed by normalised name (`data/cache/`, gitignored); user fixes saved with source=user and always win; person aliases never cached · database · aliases like Person_03 mean different people in different statements
- **Tool calling for chat** · Super gets 5 tools over `core/insights.py` (the 4 helpers + `month_overview` for advice questions), max 4 rounds, tool errors returned to the model as data · let the model see the dataframe · the model can't invent numbers it never sees, and a bad month format gets fixed by the model on the next round
- **Fallbacks for tool calling** · parse `<tool_call>` tags from content if the server doesn't return `tool_calls`; `CHAT_MODE=plan` asks for a JSON plan of helper calls instead · fail · keeps chat working whatever the endpoint does; plan mode costs 2 calls and can't chain tools
- **Number check** · `llm/verify.py` pulls every number out of chat and coach text and flags any not in the computed results (allowing rounding, sums/differences of two numbers, small counts, years); the app shows a warning · trust the prompt · makes "the model never does maths" checkable and visible to judges
- **Coach budgets** · Ultra proposes budgets, but "last month" next to each budget is filled from insights by our code · trust the model's copy · the comparison number must be exact
- **Charts** · Altair (ships with Streamlit) · Plotly · one less dependency, donut + grouped bars are enough
- **Per-session call log** · copy new entries of the global log into `st.session_state` around each call · global log only · on a deployed app several users share one process; each footer should show only that user's statement
- **Offline tests** · `tests/fake_llm.py` fake OpenAI client; tests prove Nano never sees 10-digit numbers or raw narrations and Ultra never sees transactions · mock per test · the whole LLM layer and app can be tested without a key or network
- **Nano prompt after first live eval** · general guidance (DTH/gas/CRED are bills, chains by type, "Other" as last resort) · add the eval's own merchants as few-shots · 88% → 91% overall (Nano 11/23 → 14/23) without teaching to the test set
- **Nano reasoning** · off · on · `enable_thinking=True` gave identical tokens (831+409) and accuracy, so Token Factory doesn't apply it to Nano; kept a `--thinking` flag in the eval to re-check later
- **Three more chat tools** · `sum_transactions` (filters incl. amount range), `largest_transactions` (sorted by amount), `recurring_payments` · rely on the 5 original tools · live run: "biggest 3 payments" returned the 3 newest (list is date-sorted), "chai under Rs 200" had no tool so the model guessed an average, "subscriptions" missed Jio. Sums are still pandas, via insights' own filters
- **Chat suggestions** · may only quote amounts from tool results; Hinglish questions answered in Hinglish with an example in the prompt · free-form tips · the model invented targets (Rs 1,500 / 4,000 / 666) that the number check flagged in 3 of 10 answers
- **Stricter number check** · a number passes if it's in the tool results/question within Rs 1, or is a sum/difference of two numbers the answer itself quotes · any pair of source numbers, ±0.5% · second live run: "save ~Rs 2,000–3,000 / ~Rs 4,000" passed the old check because with ~400 source numbers almost any round figure is some difference by chance. Replaying that answer, the new check flags "4,000"; the prompt now also forbids halving/rounding amounts
- **Chat category hints** · prompt spells out Eating out vs Food delivery and "doston ko bheja" = payments to people (cp_type=person) · rely on tool descriptions · live run: "chai and snacks" was summed as Food delivery and the Hinglish transfers question returned nothing
- **Language choice in code** · detect Hinglish (2+ common Hindi words) and add "Answer in Hinglish/English" to the request · prompt rule only · live runs flipped both ways (English question answered in Hinglish, then a Hinglish one in English); a small word list is deterministic and free
- **"Money to friends"** · category "Transfers to people" · cp_type=person · rent to a landlord is also a person payment, so "doston ko bheja" came out as Rs 35,410 including Rs 18,000 rent, and the tip told the user to send less to their landlord
- **Period on every tool result** · each result says which months it covers ("ALL months combined (2026-07 to 2026-09)") and the prompt says to describe it that way · trust the model · live run: a 3-month total (302 payments) was reported as "In September 2026"
- **No cp_type filter for the model** · removed from tool schemas; friends = category "Transfers to people" · prompt hint only · the model kept using cp_type=person for "doston ko bheja" (Rs 35,410 incl. rent) despite the prompt
