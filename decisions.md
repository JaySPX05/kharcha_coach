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
