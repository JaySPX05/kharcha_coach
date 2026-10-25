"""Kharcha Coach — Streamlit app.

Run:  streamlit run app/main.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app.pipeline import STEPS, run_pipeline  # noqa: E402
from core.insights import compute_insights  # noqa: E402
from core.parsers import StatementError  # noqa: E402
from core.schema import CATEGORIES  # noqa: E402
from llm import client as llm_client  # noqa: E402
from llm.categorize import set_user_category  # noqa: E402
from llm.verify import format_inr  # noqa: E402

SAMPLE = ROOT / "data" / "sample" / "statement.pdf"
USD_TO_INR = 84.0  # display only

st.set_page_config(page_title="Kharcha Coach", page_icon="₹", layout="wide")


# ----------------------------------------------------------------- helpers
def rs(x: float | None) -> str:
    return "—" if x is None else f"Rs {format_inr(x)}"


def has_key() -> bool:
    try:
        if "NEBIUS_API_KEY" in st.secrets:  # Streamlit Cloud / HF secrets
            os.environ.setdefault("NEBIUS_API_KEY", st.secrets["NEBIUS_API_KEY"])
    except Exception:  # noqa: BLE001 — no secrets file locally is fine
        pass
    return bool(os.getenv("NEBIUS_API_KEY"))


def track_calls(fn, *a, **kw):
    """Run fn and copy any model calls it made into this session's log."""
    start = len(llm_client.CALL_LOG)
    try:
        return fn(*a, **kw)
    finally:
        st.session_state.calls += llm_client.CALL_LOG[start:]


def init_state():
    for k, v in {"result": None, "df": None, "calls": [], "chat": [], "coach": {},
                 "source_name": None, "error": None}.items():
        st.session_state.setdefault(k, v)


def load(file_bytes: bytes, name: str, password: str | None):
    st.session_state.update(result=None, df=None, calls=[], chat=[], coach={}, error=None)
    bar = st.progress(0.0, text="Starting…")

    def on_step(i, label):
        bar.progress(i / len(STEPS), text=f"{i + 1}/{len(STEPS)} · {label}")

    try:
        res = track_calls(run_pipeline, file_bytes, name, password, use_llm=has_key(), on_step=on_step)
    except StatementError as e:
        st.session_state.error = str(e)
        bar.empty()
        return
    except Exception as e:  # noqa: BLE001
        st.session_state.error = f"Something went wrong while reading this statement: {type(e).__name__}: {e}"
        bar.empty()
        return
    bar.progress(1.0, text="Done")
    bar.empty()
    st.session_state.update(result=res, df=res.df, source_name=name)


def apply_override(merchant: str, cp_type: str, category: str):
    df = st.session_state.df
    mask = df["counterparty"] == merchant
    df.loc[mask, "category"] = category
    df.loc[mask, "category_source"] = "user"
    if cp_type != "person":  # aliases change per statement, so only real merchant names are cached
        set_user_category(merchant, category)
    st.session_state.df = df
    st.session_state.coach = {}


# ----------------------------------------------------------------- sidebar
init_state()
with st.sidebar:
    st.markdown("## ₹ Kharcha Coach")
    st.caption("Your bank statement, decoded, private, and coached.")
    up = st.file_uploader("Upload a statement", type=["pdf", "csv"],
                          help="PDF or CSV from your bank. Password-protected PDFs work too.")
    pw = st.text_input("PDF password (if any)", type="password",
                       help="Many Indian banks lock statements with a password like your DOB or customer ID.")
    c1, c2 = st.columns(2)
    if c1.button("Analyse", type="primary", disabled=up is None, width="stretch"):
        load(up.getvalue(), up.name, pw or None)
    if c2.button("Try sample", width="stretch",
                 help="A synthetic 3-month statement of a Bengaluru student. No real data."):
        load(SAMPLE.read_bytes(), SAMPLE.name, None)

    st.divider()
    st.markdown("**Privacy**")
    st.caption("Parsing, UPI decoding and masking run before any AI call. Account numbers, phone numbers, "
               "UPI reference numbers and friends' names never reach a model. Nothing is stored after you close the tab.")
    if not has_key():
        st.warning("No NEBIUS_API_KEY set: running without AI. Categories come from rules only; chat and coach are off.")


# ----------------------------------------------------------------- empty / error
if st.session_state.error:
    msg = st.session_state.error
    if "password" in msg.lower():
        st.error(f"🔒 {msg}\n\nEnter the PDF password in the sidebar and press **Analyse** again.")
    else:
        st.error(msg)

if st.session_state.df is None:
    st.title("Where did my money go?")
    st.markdown(
        "Upload a bank statement to see where your money went, ask questions in English or Hinglish, "
        "and get a plan for next month.\n\n"
        "No statement handy? Press **Try sample** in the sidebar.")
    a, b, c = st.columns(3)
    a.markdown("**1 · Decode**  \n`UPI/DR/…/SWIGGY/YESB/swiggy@ybl` → *Swiggy, Food delivery*")
    b.markdown("**2 · Ask**  \n*\"Kitna paisa doston ko bheja?\"* → an exact number, computed, never guessed")
    c.markdown("**3 · Coach**  \nBudgets and 3 actions with rupee amounts from your own data")
    st.stop()


# ----------------------------------------------------------------- data ready
df: pd.DataFrame = st.session_state.df
months = sorted(pd.to_datetime(df["date"]).dt.strftime("%Y-%m").unique())
month = st.sidebar.selectbox("Month", months[::-1], index=0,
                             format_func=lambda m: pd.Period(m).strftime("%B %Y"))
ins = compute_insights(df, month)
summary = ins["summary"]

tab_dash, tab_ask, tab_coach, tab_ai = st.tabs(["📊 Dashboard", "💬 Ask", "🧭 Coach report", "🔍 What the AI saw"])

# ================================================================= DASHBOARD
with tab_dash:
    st.subheader(pd.Period(month).strftime("%B %Y"))
    spend_cats = [c for c in ins["by_category"] if c["category"] != "Income"]
    biggest = spend_cats[0] if spend_cats else None
    earlier = [m for m in ins["monthly"] if m["month"] < month]
    prev = earlier[-1] if earlier else None
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Spent", rs(summary["spend"]),
              delta=rs(summary["spend"] - prev["spend"]) if prev else None, delta_color="inverse")
    k2.metric("Received", rs(summary["income"]))
    sr = summary["savings_rate"]
    k3.metric("Savings rate", "—" if sr is None else f"{sr:.0f}%",
              help="(received − spent) ÷ received. Negative means you spent more than came in.")
    k4.metric("Biggest category", biggest["category"] if biggest else "—",
              delta=rs(biggest["total"]) if biggest else None, delta_color="off")

    left, right = st.columns([1, 1])
    with left:
        st.markdown("**Spend by category**")
        cat_df = pd.DataFrame(spend_cats)
        if not cat_df.empty:
            donut = alt.Chart(cat_df).mark_arc(innerRadius=70).encode(
                theta="total:Q",
                color=alt.Color("category:N", sort=alt.SortField("total", order="descending"),
                                legend=alt.Legend(title=None, orient="bottom", columns=2)),
                tooltip=["category", alt.Tooltip("total:Q", format=",.0f", title="Rs"), "count",
                         alt.Tooltip("share_pct:Q", title="% of spend")],
            ).properties(height=340)
            st.altair_chart(donut, width="stretch")
    with right:
        st.markdown("**Month by month**")
        mdf = pd.DataFrame(ins["monthly"]).melt(id_vars="month", value_vars=["income", "spend"],
                                                 var_name="type", value_name="amount")
        bars = alt.Chart(mdf).mark_bar().encode(
            x=alt.X("month:N", title=None), xOffset="type:N",
            y=alt.Y("amount:Q", title="Rs"),
            color=alt.Color("type:N", scale=alt.Scale(domain=["income", "spend"], range=["#2F9E77", "#E8590C"]),
                            legend=alt.Legend(title=None, orient="bottom")),
            tooltip=["month", "type", alt.Tooltip("amount:Q", format=",.0f")],
        ).properties(height=340)
        st.altair_chart(bars, width="stretch")

    st_ = ins["small_ticket"]
    if st_["count"]:
        top_small = ", ".join(f"{c['category']} {rs(c['total'])}" for c in st_["by_category"][:3])
        st.info(f"☕ **Small payments add up.** {st_['count']} payments under {rs(st_['threshold'])} "
                f"came to **{rs(st_['total'])}** this month — {top_small}.")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Recurring & subscriptions**")
        if ins["recurring"]:
            for r in ins["recurring"]:
                st.markdown(f"- {r['counterparty']} · {rs(r['amount'])}/month · {r['category']}")
        else:
            st.caption("None found yet — needs 2+ months of data.")
    with c2:
        t = ins["transfers_to_people"]
        st.markdown("**Sent to people**")
        st.markdown(f"{rs(t['total'])} in {t['count']} transfers")
        for p in t["top"][:3]:
            st.caption(f"{p['counterparty']}: {rs(p['total'])} ({p['count']})")
    with c3:
        st.markdown("**Unusual payments**")
        if ins["unusual"]:
            for u in ins["unusual"][:4]:
                st.markdown(f"- {u['date']} · {u['counterparty']} · {rs(u['amount'])} "
                            f"(usual {rs(u['category_median'])})")
        else:
            st.caption("Nothing out of the ordinary.")

    st.markdown("**Top merchants**")
    tm = pd.DataFrame(ins["top_merchants"])
    if not tm.empty:
        st.dataframe(tm.rename(columns={"merchant": "Merchant", "total": "Total (Rs)", "count": "Payments"}),
                     hide_index=True, width="stretch")

    with st.expander("✏️ Fix a category", expanded=False):
        st.caption("Wrong category? Change it here. Merchant fixes are remembered for future statements.")
        merch = (df[df["direction"] == "debit"]
                 .groupby(["counterparty", "cp_type"], as_index=False)
                 .agg(category=("category", "first"), source=("category_source", "first"),
                      total=("amount", "sum"), payments=("amount", "size"))
                 .sort_values("total", ascending=False))
        edited = st.data_editor(
            merch, hide_index=True, width="stretch", key="cat_editor",
            disabled=["counterparty", "cp_type", "source", "total", "payments"],
            column_config={
                "counterparty": "Merchant / person",
                "cp_type": "Type",
                "category": st.column_config.SelectboxColumn("Category", options=list(CATEGORIES), required=True),
                "source": st.column_config.TextColumn("Decided by", help="rule · llm (Nemotron Nano) · cache · user"),
                "total": st.column_config.NumberColumn("Total (Rs)", format="%.0f"),
            })
        changed = edited[edited["category"] != merch["category"]]
        if len(changed):
            for _, r in changed.iterrows():
                apply_override(r["counterparty"], r["cp_type"], r["category"])
            st.rerun()

# ================================================================= ASK
with tab_ask:
    if not has_key():
        st.info("Chat needs a Token Factory API key (NEBIUS_API_KEY).")
    else:
        from llm.chat import answer

        st.caption("Ask in English or Hinglish. Every number is computed by our code — Nemotron Super only "
                   "decides which calculation to run and explains the result.")
        examples = [f"How much did I spend on Swiggy in {pd.Period(month).strftime('%B')}?",
                    "Kitna paisa doston ko bheja?", "What can I cut to save 3000 next month?",
                    f"Compare {pd.Period(months[-2]).strftime('%B') if len(months) > 1 else 'last month'} and "
                    f"{pd.Period(month).strftime('%B')}"]
        cols = st.columns(len(examples))
        clicked = None
        for col, q in zip(cols, examples):
            if col.button(q, width="stretch"):
                clicked = q

        for turn in st.session_state.chat:
            with st.chat_message(turn["role"]):
                st.markdown(turn["content"])
                if turn["role"] == "assistant" and turn.get("meta"):
                    m = turn["meta"]
                    names = ", ".join(c["name"] for c in m["tool_calls"]) or "no tools"
                    st.caption(f"Computed from {m['txn_count']} transactions · tools: {names}")
                    if m["unverified"]:
                        st.warning(f"Check these numbers — not found in the computed results: {', '.join(m['unverified'])}")
                    with st.expander("Show the calculation"):
                        st.json(m["tool_calls_full"], expanded=False)

        q = st.chat_input("Ask about your spending…") or clicked
        if q:
            history = [{"role": t["role"], "content": t["content"]} for t in st.session_state.chat]
            st.session_state.chat.append({"role": "user", "content": q})
            with st.spinner("Nemotron Super is working it out…"):
                try:
                    r = track_calls(answer, q, df, history)
                    meta = {**r, "tool_calls_full": [{"tool": c["name"], "arguments": c["arguments"], "result": res}
                                                     for c, res in zip(r["tool_calls"], r["numbers_used"])]}
                    st.session_state.chat.append({"role": "assistant", "content": r["text"] or "_(no answer)_",
                                                  "meta": meta})
                except Exception as e:  # noqa: BLE001
                    st.session_state.chat.append({"role": "assistant",
                                                  "content": f"Sorry, the model call failed ({type(e).__name__}). Try again."})
            st.rerun()

# ================================================================= COACH
with tab_coach:
    if not has_key():
        st.info("The coach report needs a Token Factory API key (NEBIUS_API_KEY).")
    else:
        from llm.coach import coach_report

        goal = st.text_input("Your goal (optional)", placeholder="Save Rs 5,000 for a trip in December")
        key = f"{month}|{goal.strip()}"
        if st.button("Write my coach report", type="primary"):
            with st.spinner("Nemotron Ultra is reasoning over your month… (this is the slow, careful one)"):
                try:
                    st.session_state.coach[key] = track_calls(coach_report, ins, goal or None)
                except Exception as e:  # noqa: BLE001
                    st.error(f"Couldn't write the report: {e}")
        rep = st.session_state.coach.get(key)
        if rep is None:
            st.caption("Nemotron Ultra reads only this month's totals (never individual transactions) "
                       "and writes budgets plus three specific actions.")
        else:
            st.markdown(f"### {pd.Period(month).strftime('%B %Y')} in a nutshell")
            st.write(rep["summary"])
            st.markdown("### Three things to do next month")
            for i, a in enumerate(rep["actions"], 1):
                with st.container(border=True):
                    st.markdown(f"**{i}. {a['title']}** — impact about **{rs(a['rupee_impact'])}**")
                    st.write(a.get("detail", ""))
            st.markdown("### Budgets")
            bdf = pd.DataFrame(rep["budgets"])[["category", "last_month", "budget"]]
            bdf["change"] = bdf["budget"] - bdf["last_month"]
            st.dataframe(bdf.rename(columns={"category": "Category", "last_month": "Spent this month (Rs)",
                                             "budget": "Budget next month (Rs)", "change": "Change (Rs)"}),
                         hide_index=True, width="stretch",
                         column_config={c: st.column_config.NumberColumn(format="%.0f") for c in
                                        ["Spent this month (Rs)", "Budget next month (Rs)", "Change (Rs)"]})
            if rep.get("watch_outs"):
                st.markdown("### Watch out for")
                for w in rep["watch_outs"]:
                    st.markdown(f"- {w}")
            if rep.get("unverified"):
                st.warning("These figures could not be traced to your data — treat them with care: "
                           + ", ".join(rep["unverified"]))
            else:
                st.caption("✅ Every rupee figure above traces back to numbers computed from your statement.")

# ================================================================= WHAT THE AI SAW
with tab_ai:
    st.markdown("Everything below is exactly what was sent to a model. Raw narrations, account numbers, "
                "phone numbers, UPI reference numbers and real names were masked on this device first.")
    calls = st.session_state.calls
    nano = [c for c in calls if c.tier == "nano" and c.payload_preview]
    sup = [c for c in calls if c.tier == "super"]
    ult = [c for c in calls if c.tier == "ultra" and c.payload_preview]

    st.markdown(f"**Nemotron Nano — merchant names only** ({len(nano)} call(s))")
    if nano:
        st.code("\n".join(m for c in nano for m in c.payload_preview["merchants"]), language=None)
    else:
        st.caption("No merchants needed the model — rules or the cache handled all of them.")

    st.markdown(f"**Nemotron Super — your questions + tool results** ({len(sup)} call(s))")
    for turn in st.session_state.chat:
        if turn["role"] == "assistant" and turn.get("meta"):
            st.json(turn["meta"]["tool_calls_full"], expanded=False)
    if not sup:
        st.caption("No questions asked yet.")

    st.markdown(f"**Nemotron Ultra — monthly totals only** ({len(ult)} call(s))")
    if ult:
        st.json(ult[-1].payload_preview, expanded=False)
    else:
        st.caption("No coach report yet.")

    st.markdown("**Sample of the redacted data** (what stays on this device after masking)")
    st.dataframe(df[["date", "narration", "counterparty", "vpa", "cp_type", "category"]]
                 .sample(min(8, len(df)), random_state=1), hide_index=True, width="stretch")

# ----------------------------------------------------------------- footer
calls = st.session_state.calls
u = llm_client.usage_summary(calls)
by = " · ".join(f"{t}: {v['calls']} call(s), {v['tokens']:,} tok, {v['avg_latency_s']}s avg"
                for t, v in u["by_tier"].items())
st.divider()
st.caption(f"Model calls for this statement: **{u['calls']}** · tokens {u['prompt_tokens'] + u['completion_tokens']:,} · "
           f"est. cost **${u['cost_usd']:.4f}** (≈ Rs {u['cost_usd'] * USD_TO_INR:.2f})"
           + (f"  \n{by}" if by else "")
           + "  \nNemotron Nano · Super · Ultra via Nebius Token Factory")
