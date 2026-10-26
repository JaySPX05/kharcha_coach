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
from core.insights import compute_insights, daily_spend  # noqa: E402
from core.parsers import StatementError  # noqa: E402
from core.schema import CATEGORIES  # noqa: E402
from llm import client as llm_client  # noqa: E402
from llm.verify import format_inr  # noqa: E402

SAMPLE = ROOT / "data" / "sample" / "statement.pdf"
USD_TO_INR = 84.0  # display only

st.set_page_config(page_title="Kharcha Coach", page_icon="₹", layout="wide")

# Theme "Ocean teal". Page and sidebar colours live in .streamlit/config.toml; keep the two in sync.
# Everything config.toml can't express is here, so a re-theme is this block plus config.toml.
_DARK = getattr(st.context.theme, "type", "light") == "dark"
C = {
    "accent": "#0C8599",            # charts, bars, rules
    "accent_text": "#3BC9DB" if _DARK else "#0B7285",  # accent as text: AA on the page
    "second": "#F08C00",            # spend, logo, highlights
    "second_text": "#FFB54D" if _DARK else "#A35F00",
    "on_second": "#0B2E33",         # text on a second-colour fill
    "page": "#0A1A1D" if _DARK else "#F3F7F7",
    "line": "#21393D" if _DARK else "#D3E0E1",
    "muted": "#93A9AC" if _DARK else "#53686B",
    "cal_low": "#1A3034" if _DARK else "#E0EAEB",
    "cal_mid": "#F7C27A",
    "ink": "#122326",
    # category colours, same order as chartCategoricalColors in config.toml
    "cats": ["#0C8599", "#F08C00", "#5C7CFA", "#E64980", "#74B816", "#845EF7", "#868E96", "#15AABF",
             "#FAB005", "#ADB5BD"],
}


def _text_on(hex_colour: str) -> str:
    """White or dark ink, whichever reads better on this fill."""
    r, g, b = (int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return C["ink"] if 0.299 * r + 0.587 * g + 0.114 * b > 0.6 else "white"

ACCENT_RGB, SECOND_RGB = "12,133,153", "240,140,0"
st.html(f"""<style>
:root {{
  --kc-accent: {C["accent"]};
  --kc-accent-text: {C["accent_text"]};
  --kc-tint: rgba({"59,201,219,.12" if _DARK else ACCENT_RGB + ",.08"});
  --kc-line: {C["line"]};
  --kc-muted: {C["muted"]};
  --kc-second: {C["second"]};
}}
/* rupee figures line up column to column */
[data-testid="stMetricValue"], [data-testid="stDataFrame"], .kc-num {{ font-variant-numeric: tabular-nums; }}
[data-testid="stMetricValue"] {{ letter-spacing: -0.02em; }}
h1, h2, h3, .kc-hero h1 {{ letter-spacing: -0.025em; text-wrap: balance; }}
p, li {{ text-wrap: pretty; }}
[data-testid="stMetric"] {{ background: var(--kc-tint); border-color: transparent !important; }}
button[data-baseweb="tab"] p {{ font-weight: 600; }}
.stButton button {{ transition: transform .15s cubic-bezier(.16,1,.3,1), filter .15s; }}
.stButton button:active {{ transform: translateY(1px) scale(.99); }}

.kc-brand {{ display: flex; align-items: center; gap: .7rem; margin: .25rem 0 .35rem; }}
.kc-mark {{ width: 2.4rem; height: 2.4rem; border-radius: .75rem; display: grid; place-items: center;
  background: var(--kc-second); color: {C["on_second"]}; font: 700 1.35rem/1 "Bricolage Grotesque", sans-serif; }}
.kc-word {{ font: 700 1.3rem/1.1 "Bricolage Grotesque", sans-serif; letter-spacing: -0.02em; }}
.kc-word small {{ display: block; font: 500 .78rem/1.4 Geist, sans-serif; letter-spacing: 0; opacity: .72; }}

.kc-hero {{ display: grid; grid-template-columns: 1.05fr 1fr; gap: 3rem; align-items: center;
  padding: 2.5rem 0 2rem; }}
.kc-hero h1 {{ font: 750 clamp(2.4rem, 4.6vw, 3.9rem)/1.02 "Bricolage Grotesque", sans-serif; margin: 0 0 1.1rem; padding: 0; }}
.kc-hero h1 em {{ font-style: normal; color: var(--kc-accent-text); }}
.kc-lede {{ font-size: 1.12rem; line-height: 1.6; max-width: 34rem; color: var(--kc-muted); margin: 0 0 1.4rem; }}
.kc-hint {{ display: inline-flex; gap: .5rem; align-items: center; padding: .55rem .9rem; border-radius: .75rem;
  background: var(--kc-tint); color: var(--kc-accent-text); font-weight: 600; font-size: .95rem; }}
.kc-specimen {{ margin: 0; padding: 1.6rem; border: 1px solid var(--kc-line); border-radius: 1.25rem;
  background: linear-gradient(180deg, var(--kc-tint), transparent 70%); }}
.kc-label {{ font-size: .78rem; font-weight: 600; color: var(--kc-muted); margin-bottom: .45rem; }}
.kc-raw {{ display: block; font: 500 .9rem/1.5 "Geist Mono", monospace; padding: .8rem 1rem; border-radius: .75rem;
  border: 1px dashed var(--kc-line); overflow-wrap: anywhere; color: var(--kc-muted); }}
/* ledger-book ruling: the khata the theme is named after */
[data-testid="stSidebar"] > div:first-child {{
  background-image:
    linear-gradient(90deg, transparent 1.15rem, rgba({SECOND_RGB},.5) 1.15rem, rgba({SECOND_RGB},.5) calc(1.15rem + 1px), transparent calc(1.15rem + 1px)),
    repeating-linear-gradient(180deg, transparent 0 1.75rem, rgba(227,241,242,.045) 1.75rem calc(1.75rem + 1px)); }}
.kc-hero {{ position: relative; }}
.kc-hero::before {{ content: ""; position: absolute; inset: -3rem -2rem auto 40%; height: 26rem; z-index: -1;
  pointer-events: none; filter: blur(10px);
  background: radial-gradient(closest-side, rgba({ACCENT_RGB},{".22" if _DARK else ".13"}), transparent),
              radial-gradient(closest-side at 80% 70%, rgba({SECOND_RGB},{".16" if _DARK else ".14"}), transparent); }}
.kc-raw {{ line-height: 1.6rem !important; background: repeating-linear-gradient(180deg, transparent 0 calc(1.6rem - 1px), var(--kc-line) calc(1.6rem - 1px) 1.6rem) 0 .8rem / 100% 1.6rem; }}
.kc-flow {{ position: relative; height: 2.2rem; margin: .35rem 0 .35rem 1.2rem; border-left: 2px solid var(--kc-accent); }}
.kc-flow::after {{ content: ""; position: absolute; left: -5px; top: 0; width: 8px; height: 8px; border-radius: 50%;
  background: var(--kc-second); box-shadow: 0 0 0 4px rgba({SECOND_RGB},.22); }}
.kc-ico {{ font-family: "Material Symbols Rounded"; font-size: 1.35rem; line-height: 1; display: inline-grid;
  place-items: center; width: 2.6rem; height: 2.6rem; border-radius: .75rem; margin-bottom: .8rem;
  background: var(--kc-tint); color: var(--kc-accent-text); font-weight: 400; }}
.kc-verbs div:nth-child(2) .kc-ico {{ background: rgba({SECOND_RGB},.16); color: {C["second_text"]}; }}
.kc-decoded {{ display: flex; flex-wrap: wrap; gap: .6rem; align-items: center; padding: 1rem; border-radius: .75rem;
  border: 1px solid var(--kc-line); }}
.kc-merchant {{ font: 700 1.25rem/1 "Bricolage Grotesque", sans-serif; }}
.kc-chip {{ padding: .25rem .6rem; border-radius: .5rem; background: var(--kc-tint); color: var(--kc-accent-text);
  font-weight: 600; font-size: .85rem; }}
.kc-decoded .kc-num {{ margin-left: auto; font: 600 1.15rem/1 Geist, sans-serif; }}
.kc-masked {{ margin-top: .7rem; font: 500 .8rem/1.4 "Geist Mono", monospace; color: var(--kc-muted); }}
.kc-callout {{ padding: .95rem 1.2rem; border-radius: .75rem; background: var(--kc-tint);
  border-left: 3px solid var(--kc-second); line-height: 1.55; }}
.kc-callout b {{ color: var(--kc-accent-text); }}
.kc-verbs {{ display: grid; grid-template-columns: repeat(3, 1fr); border-top: 1px solid var(--kc-line); margin-top: .5rem; }}
.kc-verbs div {{ padding: 1.3rem 1.5rem 0 0; }}
.kc-verbs div + div {{ padding-left: 1.5rem; border-left: 1px solid var(--kc-line); }}
.kc-verbs b {{ display: block; font: 700 1.15rem/1.2 "Bricolage Grotesque", sans-serif; margin-bottom: .35rem; }}
.kc-verbs span:not(.kc-ico) {{ color: var(--kc-muted); line-height: 1.55; }}
.kc-verbs code {{ font-size: .8rem; }}
@media (max-width: 768px) {{
  .kc-hero {{ grid-template-columns: 1fr; gap: 1.75rem; padding-top: 1rem; }}
  .kc-verbs {{ grid-template-columns: 1fr; }}
  .kc-verbs div, .kc-verbs div + div {{ padding: 1rem 0; border-left: 0; border-bottom: 1px solid var(--kc-line); }}
}}
@media (prefers-reduced-motion: no-preference) {{
  .kc-hero > * {{ animation: kc-rise .6s cubic-bezier(.16,1,.3,1) both; }}
  .kc-hero > :nth-child(2) {{ animation-delay: .08s; }}
  @keyframes kc-rise {{ from {{ opacity: 0; transform: translateY(14px); }} }}
  /* the pulse travels from raw narration to decoded row: decoding happens here, on device */
  .kc-flow::after {{ animation: kc-travel 2.2s cubic-bezier(.65,0,.35,1) infinite; }}
  @keyframes kc-travel {{ 0% {{ transform: translateY(0); opacity: 0; }} 15%, 80% {{ opacity: 1; }}
    100% {{ transform: translateY(calc(2.2rem - 8px)); opacity: 0; }} }}
}}
</style>""")


# ----------------------------------------------------------------- helpers
def rs(x: float | None) -> str:
    return "n/a" if x is None else f"₹{format_inr(x)}"


def has_key() -> bool:
    try:
        if "NEBIUS_API_KEY" in st.secrets:  # Streamlit Cloud / HF secrets
            os.environ.setdefault("NEBIUS_API_KEY", st.secrets["NEBIUS_API_KEY"])
    except Exception:  # noqa: BLE001 — no secrets file locally is fine
        pass
    return bool(os.getenv("NEBIUS_API_KEY"))


def track_calls(fn, *a, **kw):
    """Run fn and add the model calls it made (this visitor's only) to this session's log."""
    try:
        out, calls = llm_client.collect_calls(fn, *a, **kw)
    except Exception as e:
        st.session_state.calls += getattr(e, "calls", [])
        raise
    st.session_state.calls += calls
    return out


def init_state():
    for k, v in {"df": None, "calls": [], "chat": [], "coach": {},
                 "source_name": None, "error": None}.items():
        st.session_state.setdefault(k, v)


def load(file_bytes: bytes, name: str, password: str | None):
    st.session_state.update(df=None, calls=[], chat=[], coach={}, error=None)
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
    st.session_state.update(df=res, source_name=name)


def apply_override(merchant: str, category: str):
    df = st.session_state.df
    mask = df["counterparty"] == merchant
    df.loc[mask, "category"] = category
    df.loc[mask, "category_source"] = "user"
    st.session_state.df = df  # this session only: one visitor's fix must not relabel everyone's
    st.session_state.coach = {}


# ----------------------------------------------------------------- sidebar
init_state()
with st.sidebar:
    st.html('<div class="kc-brand"><div class="kc-mark">₹</div>'
            '<div class="kc-word">Kharcha Coach<small>Your bank statement, decoded, private, and coached.</small></div></div>')
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
    st.markdown(":material/shield_lock: **Privacy**")
    st.caption("Parsing, UPI decoding and masking run before any AI call. Account numbers, phone numbers, "
               "UPI reference numbers and friends' names never reach a model. Your statement isn't stored; "
               "merchant categories are cached to save AI calls.")
    with st.expander("How your data is handled", icon=":material/policy:"):
        st.markdown("""
**What we read.** Only the statement you upload. No sign-up, no SMS access, no bank login, no tracking or analytics.

**What we keep.** Nothing from your statement. The file is read in memory and never written to disk.
Your transactions, chat and coach report live in this browser tab only and are gone when you close it.
The one thing saved is a list of merchant names and their category (for example *Zepto: Groceries*),
so the same shop isn't sent to the AI twice. It has no amounts, dates, account details or people.

**What the AI sees.** Before any AI call we mask account numbers, phone numbers, UPI reference numbers
and the names of people you paid (they become *Person_03*). The models get merchant names, amounts,
dates and categories, never the raw statement. Every number they quote is computed by our code, not by the AI.

**Who processes it.** The AI models (NVIDIA Nemotron) run on Nebius Token Factory, which may keep request
logs under its own policy. Those requests contain only the masked data above.

**Please note.** This is a hackathon demo, not financial advice. Try the synthetic sample first
if you'd rather not upload a real statement.
""")
    if not has_key():
        st.warning("No NEBIUS_API_KEY set: running without AI. Categories come from rules only; chat and coach are off.")


# ----------------------------------------------------------------- empty / error
if st.session_state.error:
    msg = st.session_state.error
    if "password" in msg.lower():
        st.error(f"{msg}\n\nEnter the PDF password in the sidebar and press **Analyse** again.",
                 icon=":material/lock:")
    else:
        st.error(msg, icon=":material/error:")

if st.session_state.df is None:
    st.html("""
<section class="kc-hero">
  <div>
    <h1>Where did my <em>money</em> go?</h1>
    <p class="kc-lede">Upload a bank statement to see where your money went, ask questions in English or Hinglish,
      and get a plan for next month.</p>
    <span class="kc-hint">No statement handy? Press Try sample in the sidebar.</span>
  </div>
  <figure class="kc-specimen" aria-label="Example: one UPI line from a statement, decoded">
    <div class="kc-label">On your statement</div>
    <code class="kc-raw">UPI/<wbr>DR/<wbr>412345678901/<wbr>SWIGGY/<wbr>YESB/<wbr>swiggy@ybl/<wbr>Payment</code>
    <div class="kc-flow" aria-hidden="true"></div>
    <div class="kc-label">In Kharcha Coach</div>
    <div class="kc-decoded">
      <span class="kc-merchant">Swiggy</span><span class="kc-chip">Food delivery</span>
      <span class="kc-num">₹349</span>
    </div>
    <div class="kc-masked">Reference sent to AI as XXXXXXXX8901</div>
  </figure>
</section>
<div class="kc-verbs">
  <div><span class="kc-ico">receipt_long</span><b>Decode</b><span><code>UPI/DR/…/SWIGGY/YESB/swiggy@ybl</code> becomes Swiggy, Food delivery</span></div>
  <div><span class="kc-ico">forum</span><b>Ask</b><span>"Kitna paisa doston ko bheja?" gets an exact number, computed, never guessed</span></div>
  <div><span class="kc-ico">insights</span><b>Coach</b><span>Budgets and 3 actions with rupee amounts from your own data</span></div>
</div>""")
    st.stop()


# ----------------------------------------------------------------- data ready
df: pd.DataFrame = st.session_state.df
months = sorted(pd.to_datetime(df["date"]).dt.strftime("%Y-%m").unique())
month = st.sidebar.selectbox("Month", months[::-1], index=0,
                             format_func=lambda m: pd.Period(m).strftime("%B %Y"))
ins = compute_insights(df, month)
summary = ins["summary"]

tab_dash, tab_ask, tab_coach, tab_ai = st.tabs([
    ":material/space_dashboard: Dashboard", ":material/forum: Ask",
    ":material/assignment: Coach report", ":material/visibility: What the AI saw"])

# ================================================================= DASHBOARD
with tab_dash:
    st.header(pd.Period(month).strftime("%B %Y"), anchor=False)
    st.caption(f"From {st.session_state.source_name} · {len(df):,} transactions decoded on this device")
    spend_cats = [c for c in ins["by_category"] if c["category"] != "Income"]
    biggest = spend_cats[0] if spend_cats else None
    earlier = [m for m in ins["monthly"] if m["month"] < month]
    prev = earlier[-1] if earlier else None
    trend = [m for m in ins["monthly"] if m["month"] <= month]  # sparklines: every month up to this one
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Spent", rs(summary["spend"]), border=True, height="stretch",
              delta=rs(summary["spend"] - prev["spend"]) if prev else None, delta_color="inverse",
              chart_data=[m["spend"] for m in trend], chart_type="area")
    k2.metric("Received", rs(summary["income"]), border=True, height="stretch",
              chart_data=[m["income"] for m in trend], chart_type="line")
    sr = summary["savings_rate"]
    k3.metric("Savings rate", "n/a" if sr is None else f"{sr:.0f}%", border=True, height="stretch",
              help="(received − spent) ÷ received. Negative means you spent more than came in.",
              chart_data=[m["savings_rate"] or 0 for m in trend], chart_type="line")
    # a description, not a metric delta: an arrow would read as "went up"
    k4.metric("Biggest category", biggest["category"] if biggest else "n/a", border=True, height="stretch",
              delta_description=f"{rs(biggest['total'])} · {biggest['share_pct']:.0f}% of spend" if biggest else None)

    cat_df = pd.DataFrame(spend_cats)
    if not cat_df.empty:
        st.markdown("**Where every ₹100 went**")
        order = cat_df["category"].tolist()
        cat_df["end"] = cat_df["share_pct"].cumsum()
        cat_df["mid"] = cat_df["end"] - cat_df["share_pct"] / 2
        cat_df["label"] = cat_df["share_pct"].map(lambda p: f"₹{p:.0f}" if p >= 6 else "")
        cat_df["ink"] = [_text_on(C["cats"][i % len(C["cats"])]) for i in range(len(cat_df))]
        base = alt.Chart(cat_df).encode(
            x=alt.X("share_pct:Q", stack="zero", axis=None, scale=alt.Scale(domain=[0, 100], nice=False)),
            tooltip=["category", alt.Tooltip("total:Q", format=",.0f", title="₹ this month"),
                     alt.Tooltip("share_pct:Q", format=".1f", title="₹ of every 100")])
        strip = base.mark_bar(height=44, cornerRadius=6, stroke=C["page"],
                              strokeWidth=2).encode(
            color=alt.Color("category:N", sort=order, scale=alt.Scale(domain=order, range=C["cats"]),
                            legend=alt.Legend(title=None, orient="bottom", direction="horizontal",
                                              columns=6, symbolType="circle", labelLimit=160)),
            order=alt.Order("end:Q"))
        labels = alt.Chart(cat_df).mark_text(fontWeight=600, fontSize=13).encode(
            x=alt.X("mid:Q", scale=alt.Scale(domain=[0, 100], nice=False)), text="label:N",
            color=alt.Color("ink:N", scale=None))
        st.altair_chart((strip + labels).properties(height=110), width="stretch")

    left, right = st.columns([1, 1])
    with left:
        st.markdown("**Day by day**")
        cal = pd.DataFrame(daily_spend(df, month))
        days = pd.to_datetime(cal["date"])
        cal["dow"] = days.dt.strftime("%a")
        cal["week"] = (days.dt.day - 1 + days.iloc[0].weekday()) // 7  # rows of a Mon-first calendar
        cal["day"] = days.dt.day
        peak = max(cal["total"].max(), 1.0)
        grid = alt.Chart(cal).encode(
            x=alt.X("dow:O", sort=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], title=None,
                    scale=alt.Scale(paddingInner=0.14),
                    axis=alt.Axis(orient="top", labelAngle=0, domain=False, ticks=False, labelPadding=8)),
            y=alt.Y("week:O", axis=None, scale=alt.Scale(paddingInner=0.14)),
            tooltip=[alt.Tooltip("date:N", title="day"), alt.Tooltip("total:Q", format=",.0f", title="₹ spent"),
                     alt.Tooltip("count:Q", title="payments")])
        cells = grid.mark_rect(cornerRadius=7).encode(
            color=alt.Color("total:Q", legend=None, scale=alt.Scale(
                domain=[0, peak * 0.5, peak],
                range=[C["cal_low"], C["cal_mid"], C["second"]], interpolate="rgb")))
        nums = grid.mark_text(fontSize=12, fontWeight=500).encode(
            text="day:Q",
            color=alt.condition(alt.datum.total > peak * 0.3, alt.value(C["ink"]),
                                alt.value(C["muted"])))
        st.altair_chart((cells + nums).properties(height=340), width="stretch")
        st.caption("The more orange a day, the more you spent.")
    with right:
        st.markdown("**Month by month**")
        mdf = pd.DataFrame(ins["monthly"]).melt(id_vars="month", value_vars=["income", "spend"],
                                                 var_name="type", value_name="amount")
        mdf["label"] = mdf["month"].map(lambda m: pd.Period(m).strftime("%b %Y"))
        bars = alt.Chart(mdf).mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5).encode(
            x=alt.X("label:N", title=None, sort=alt.SortField("month"), axis=alt.Axis(labelAngle=0)),
            xOffset="type:N",
            y=alt.Y("amount:Q", title=None),
            color=alt.Color("type:N", scale=alt.Scale(domain=["income", "spend"], range=[C["accent"], C["second"]]),
                            legend=alt.Legend(title=None, orient="bottom")),
            tooltip=[alt.Tooltip("label:N", title="month"), "type", alt.Tooltip("amount:Q", format=",.0f")],
        ).properties(height=340)
        st.altair_chart(bars, width="stretch")

    st_ = ins["small_ticket"]
    if st_["count"]:
        top_small = ", ".join(f"{c['category']} {rs(c['total'])}" for c in st_["by_category"][:3])
        st.html(f'<div class="kc-callout"><b>Small payments add up.</b> {st_["count"]} payments under '
                f'{rs(st_["threshold"])} came to <b class="kc-num">{rs(st_["total"])}</b> this month: {top_small}.</div>')

    c1, c2, c3 = st.columns(3)
    with c1.container(border=True, height="stretch"):
        st.markdown(":material/autorenew: **Recurring & subscriptions**")
        if ins["recurring"]:
            for r in ins["recurring"]:
                st.markdown(f"- {r['counterparty']} · {rs(r['amount'])}/month · {r['category']}")
        else:
            st.caption("None found yet. Needs 2+ months of data.")
    with c2.container(border=True, height="stretch"):
        t = ins["transfers_to_people"]
        st.markdown(":material/group: **Sent to people**")
        st.markdown(f"### {rs(t['total'])}")
        st.caption(f"in {t['count']} transfers")
        for p in t["top"][:3]:
            st.caption(f"{p['counterparty']}: {rs(p['total'])} ({p['count']})")
    with c3.container(border=True, height="stretch"):
        st.markdown(":material/bolt: **Unusual payments**")
        if ins["unusual"]:
            for u in ins["unusual"][:4]:
                st.markdown(f"- {u['date']} · {u['counterparty']} · {rs(u['amount'])} "
                            f"(usual {rs(u['category_median'])})")
        else:
            st.caption("Nothing out of the ordinary.")

    st.markdown("**Top merchants**")
    tm = pd.DataFrame(ins["top_merchants"])
    if not tm.empty:
        top_total = float(tm["total"].max())
        st.dataframe(tm.rename(columns={"merchant": "Merchant", "total": "Total (₹)", "count": "Payments"}),
                     hide_index=True, width="stretch",
                     column_config={"Total (₹)": st.column_config.ProgressColumn(
                         format="%.0f", min_value=0, max_value=top_total)})

    with st.expander("Fix a category", expanded=False, icon=":material/edit:"):
        st.caption("Wrong category? Change it here. Fixes apply to this session.")
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
                "total": st.column_config.NumberColumn("Total (₹)", format="%.0f"),
            })
        changed = edited[edited["category"] != merch["category"]]
        if len(changed):
            for _, r in changed.iterrows():
                apply_override(r["counterparty"], r["category"])
            st.rerun()

# ================================================================= ASK
with tab_ask:
    if not has_key():
        st.info("Chat needs a Token Factory API key (NEBIUS_API_KEY).", icon=":material/key:")
    else:
        from llm.chat import answer

        st.caption("Ask in English or Hinglish. Every number is computed by our code. Nemotron Super only "
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
                    n = m["txn_count"]
                    st.caption((f"Computed from {n} transactions · " if n else "") + f"tools: {names}")
                    if m["unverified"]:
                        st.warning(f"Check these numbers. They were not found in the computed results: "
                                   f"{', '.join(m['unverified'])}")
                    with st.expander("Show the calculation"):
                        st.json(m["tool_calls_full"], expanded=3)

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
        st.info("The coach report needs a Token Factory API key (NEBIUS_API_KEY).", icon=":material/key:")
    else:
        from llm.coach import coach_report

        goal = st.text_input("Your goal (optional)", placeholder="Save ₹5,000 for a trip in December")
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
                    st.markdown(f"**{i}. {a['title']}** · {rs(a['rupee_impact'])} spent here last month")
                    st.write(a.get("detail", ""))
            st.markdown("### Budgets")
            bdf = pd.DataFrame(rep["budgets"])[["category", "last_month", "budget"]]
            bdf["change"] = bdf["budget"] - bdf["last_month"]
            st.dataframe(bdf.rename(columns={"category": "Category", "last_month": "Spent this month (₹)",
                                             "budget": "Budget next month (₹)", "change": "Change (₹)"}),
                         hide_index=True, width="stretch",
                         column_config={c: st.column_config.NumberColumn(format="%.0f") for c in
                                        ["Spent this month (₹)", "Budget next month (₹)", "Change (₹)"]})
            if rep.get("watch_outs"):
                st.markdown("### Watch out for")
                for w in rep["watch_outs"]:
                    st.markdown(f"- {w}")
            if rep.get("unverified"):
                st.warning("These figures could not be traced to your data, so treat them with care: "
                           + ", ".join(rep["unverified"]))
            else:
                st.caption(":material/verified: Every rupee figure above traces back to numbers computed "
                           "from your statement.")

# ================================================================= WHAT THE AI SAW
with tab_ai:
    st.markdown("Everything below is exactly what was sent to a model. Raw narrations, account numbers, "
                "phone numbers, UPI reference numbers and real names were masked on this device first.")
    calls = st.session_state.calls
    nano = [c for c in calls if c.tier == "nano" and c.payload_preview]
    sup = [c for c in calls if c.tier == "super"]
    ult = [c for c in calls if c.tier == "ultra" and c.payload_preview]

    st.markdown(f"**Nemotron Nano: merchant names only** ({len(nano)} call(s))")
    if nano:
        st.code("\n".join(m for c in nano for m in c.payload_preview["merchants"]), language=None)
    else:
        st.caption("No merchants needed the model. Rules or the cache handled all of them.")

    st.markdown(f"**Nemotron Super: your questions + tool results** ({len(sup)} call(s))")
    for turn in st.session_state.chat:
        if turn["role"] == "assistant" and turn.get("meta"):
            st.json(turn["meta"]["tool_calls_full"], expanded=False)
    if not sup:
        st.caption("No questions asked yet.")

    st.markdown(f"**Nemotron Ultra: monthly totals only** ({len(ult)} call(s))")
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
           f"est. cost **${u['cost_usd']:.4f}** (≈ ₹{u['cost_usd'] * USD_TO_INR:.2f})"
           + (f"  \n{by}" if by else "")
           + "  \nNemotron Nano · Super · Ultra via Nebius Token Factory")
