# Demo video script — target 2:35 (limit 2:45)

Numbers below are from `data/sample/statement.pdf` (September 2026 unless noted) and come from
`core/insights.py`. **Before recording, re-check every figure against what the app shows** — the
category totals depend on the Nano categoriser, so only merchant figures are pre-filled here.

| Time | Voice-over | On screen |
|---|---|---|
| 0:00–0:15 | "This is what a UPI payment looks like on an Indian bank statement. A student makes two hundred of these a month. Nobody reads them — and nobody should paste them into a chatbot." | Zoom on a raw PDF page full of `UPI/DR/…/YESB/swiggy@ybl/…` lines |
| 0:15–0:30 | "Kharcha Coach reads the statement — even a password-protected PDF — and decodes every narration on your laptop." | Upload `statement.pdf` (or click **Try sample**); spinner; rows appear |
| 0:30–0:45 | "Swiggy, Rapido, the canteen, a friend — each narration becomes a merchant or a person. People become aliases like Person 3, and phone numbers and reference numbers are masked before any model sees them." | Table: raw narration column beside decoded counterparty / cp_type / masked VPA |
| 0:45–1:10 | "The dashboard. In September this student earned ₹33,460 and spent ₹40,478 — a savings rate of minus 21 percent. Spending rose every month, up ₹5,774 from August." | Dashboard: in/out bars Jul→Sep, savings-rate tile, category donut |
| 1:10–1:25 | "It finds patterns you'd miss: four recurring payments — rent, Jio, Netflix, Spotify — and 152 payments under ₹200 that add up to ₹9,495." | Recurring list; small-ticket leakage card |
| 1:25–1:45 | Type: **"How much did I spend on Swiggy in September?"** — "₹5,999 across 18 orders. That number isn't the model's maths — Nemotron Super called our pandas function and quoted it." | Chat answer; expand the tool-call / numbers-used panel |
| 1:45–2:00 | Type: **"Compare August and September."** — "Swiggy nearly doubled, from ₹3,007 to ₹5,999." | Chat answer with the compare_months result |
| 2:00–2:20 | "Nemotron Ultra writes the monthly coach report from aggregates only: budgets, three actions, and what to watch." | Scroll the coach report |
| 2:20–2:30 | "And this is everything the AI saw. No account number, no phone number, no real names." | Open the **What the AI saw** panel; highlight `Person_03`, `XXXXXXXX1301` |
| 2:30–2:45 | "Nano categorises merchants cheaply and in bulk, Super handles tool-calling chat, Ultra writes the long-form report — all on Nebius Token Factory. Kharcha Coach: your statement, decoded, private, and coached." | Architecture slide: Nano / Super / Ultra with their jobs |

## Checklist before recording
- [ ] App running on the deployed URL with the sample statement
- [ ] Both chat answers give exactly the numbers above (if not, update this script from the app)
- [ ] "What the AI saw" panel shows only redacted rows
- [ ] Screen at 1080p, browser zoom so the table is readable
