# Product feedback — Token Factory, Nebius AI Cloud, Nemotron (DRAFT)

Fill each TODO from real experience: the `[llm]` log lines, `scripts/*` output and decisions.md.
Judges value specifics over praise. Delete this line before submitting.

## Nebius Token Factory
**What worked**
- OpenAI-compatible API: the stock `openai` SDK worked by changing `base_url` only. TODO: how long from key to first call.
- TODO: measured latency per tier (from the app footer / `scripts/smoke_test.py`).

**What was confusing**
- TODO: anything about finding exact model IDs (did `/v1/models` match the catalog page?).
- TODO: whether `tool_calls` came back natively for Nemotron Super (`scripts/check_tool_calling.py`).
- TODO: whether reasoning text arrived in `content` or a separate field, and if `enable_thinking` via `chat_template_kwargs` was documented.

**Suggestions**
- TODO: e.g. show per-request cost in the response or dashboard; document reasoning toggles per model.

## Nemotron models
- Nano: TODO categoriser accuracy, JSON reliability (how often the retry fired).
- Super: TODO tool-call reliability on the 10 test questions, Hinglish quality.
- Ultra: TODO report quality, latency, how often the number check flagged something.

## Nebius AI Cloud
- TODO: Serverless Endpoints deploy experience, or why we fell back to another host.
