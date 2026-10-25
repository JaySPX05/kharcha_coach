# Product feedback — Nebius Token Factory and NVIDIA Nemotron

From building Kharcha Coach on Oct 24–30, 2026. Every point below comes from our own logs and test scripts.

## Nebius Token Factory

**What worked**
- **Drop-in OpenAI compatibility.** The stock `openai` Python SDK worked by changing `base_url` and the key. Native tool calling worked for Nemotron Super on the first try (`tool_calls` returned with correct arguments, 1.6 s).
- **Model IDs from `/v1/models` matched the catalog**, and listing them made a quick check that `.env` was right (`scripts/list_models.py`).
- **Fast and cheap for this workload.** Nano categorised a 40-merchant batch in 2.2 s for $0.00015; Super averaged 1.1–1.5 s per call; 10 chat questions (20 calls, ~65k tokens) cost about $0.02.

**What was confusing or got in the way**
- **529 "System is overloaded"** appeared several times in one evening on Super (3 of 20 calls in one run). It was not in the status codes we expected to retry, so the first run crashed. Documenting 529 as retryable (and a suggested backoff) next to 429 would help.
- **Reasoning text in `content`.** With `enable_thinking: false`, Super still put a reasoning-style sentence in `content` on tool-call turns ("We need total spend for merchant Swiggy… Use spend_by tool."). Harmless on tool turns, but it would show up in a UI if a client displayed it.
- **`enable_thinking` had no visible effect on Nano.** Turning it on produced identical token counts (831 in / 409 out) and identical output, so either it isn't applied for that model or reasoning tokens aren't reported. A per-model table of which `chat_template_kwargs` are supported would save guesswork.

**Suggestions**
- Return the cost of each request (or a running total) alongside `usage`. We computed it ourselves from the price list to show "cost per statement" in the app.
- List supported reasoning controls (on/off, low-effort, budgets) per model on the model page.

## Nemotron models
- **Nano** (categoriser): 91% accuracy on 100 hand-labelled Indian merchants with rules + Nano; on the 23 hardest names Nano alone got 14/23 (61%). JSON output was valid every time; the retry for bad JSON never fired. Its main weakness was choosing "Other" for recognisable but regional brands (CTR, Nayara, Indane), which clearer category guidance partly fixed (88% → 91%).
- **Super** (tool-calling chat): chose a sensible tool in 10/10 test questions and chained calls when needed (e.g. 4× `compare_months`). It handled Hinglish well once we told it which language to answer in. Without explicit rules it sometimes invented "suggested" targets (Rs 1,500 / Rs 4,000) and once labelled a 3-month total as "September", so we added a number check and period labels on every tool result.
- **Ultra** (coach report): returned a valid report and a specific, well-grounded summary (deficit, top 3 categories, merchant-level actions). One report took 14.7 s and 8,033 tokens ($0.018), fine behind a spinner for a once-a-month report. It once computed a ratio itself ("2.8× higher on weekends"), which we now forbid in the prompt. After that change it quoted the underlying amounts instead ("Rs 2,573 per day on weekends vs Rs 904 on weekdays"); our number check still flagged one self-chosen threshold ("visits over Rs 100").

## Hosting
- We host the Streamlit app on Streamlit Community Cloud for speed before the deadline; it calls Token Factory at runtime. A Dockerfile is included for a container deploy on Nebius.
