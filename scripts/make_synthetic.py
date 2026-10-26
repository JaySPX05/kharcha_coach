"""Generate a synthetic 3-month statement (Jul-Sep 2026) for a Bengaluru student.

Writes, from the same seeded transactions:
  data/sample/statement.csv / .pdf     narration style A (SBI-like, slash separated)
  data/sample/statement_b.csv / .pdf   narration style B (HDFC-like, hyphen separated)

The CSVs carry the full schema with ground-truth decoded + redacted columns
(category columns empty). The PDFs carry only what a bank prints.
All people, phone numbers and VPAs are fake.
"""

import calendar
import random
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
from fpdf import FPDF

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so `python scripts/...` can import core
from core.schema import COLUMNS, make_txn_id  # noqa: E402

SEED = 42
MONTHS = ((2026, 7), (2026, 8), (2026, 9))
OPENING_BALANCE = 12000.0
OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "sample"

# display name, name printed in narration, vpa, payee IFSC, min Rs, max Rs, weight, weekend boost
MERCHANTS = (
    ("Swiggy", "SWIGGY", "swiggy@ybl", "YESB0YBLUPI", 150, 450, 8, 1.6),
    ("Zomato", "ZOMATO", "zomato@hdfcbank", "HDFC0MERUPI", 150, 500, 6, 1.6),
    ("Zepto", "ZEPTO MARKETPLACE", "zeptomarketplace@ybl", "YESB0YBLUPI", 80, 600, 5, 1.0),
    ("Blinkit", "BLINKIT", "blinkit.payu@hdfcbank", "HDFC0MERUPI", 80, 500, 4, 1.0),
    ("Rapido", "RAPIDO", "rapido@axisbank", "UTIB0000553", 40, 150, 12, 1.0),
    ("Namma Metro", "BMRCL NAMMA METRO", "nammametro.bmrcl@sbi", "SBIN0000813", 30, 60, 14, 0.4),
    ("Sri Lakshmi Tea Stall", "SRI LAKSHMI TEA STALL", "Q648213759@ybl", "YESB0YBLUPI", 15, 40, 22, 0.6),
    ("Chai Point", "CHAI POINT", "chaipoint@icici", "ICIC0DC0099", 25, 90, 8, 1.0),
    ("Bhaiya Chai Corner", "BHAIYA CHAI CORNER", "paytmqr5kq2m8@paytm", "PYTM0123456", 15, 35, 14, 0.6),
    ("College Canteen", "PES CANTEEN", "pescanteen@okaxis", "UTIB0001234", 40, 120, 20, 0.2),
    ("Amazon", "AMAZON PAY", "amazon@apl", "UTIB0000100", 300, 2000, 1, 1.2),
    ("Myntra", "MYNTRA DESIGNS", "myntra@icici", "ICIC0DC0099", 500, 1500, 1, 1.2),
)
# day of month, display name, narration name, vpa, IFSC, amount
SUBSCRIPTIONS = (
    (10, "Spotify", "SPOTIFY INDIA", "spotify@hdfcbank", "HDFC0MERUPI", 119.0),
    (18, "Netflix", "NETFLIX", "netflix@icici", "ICIC0DC0099", 199.0),
    (22, "Jio Recharge", "RELIANCE JIO", "jiorecharge@ybl", "YESB0YBLUPI", 299.0),
)
# key, real name (fake), vpa, IFSC. Phone numbers use a 90000 prefix to look clearly fake.
PEOPLE = {
    "parent": ("Suresh Rao", None, "CNRB0001234"),
    "landlord": ("Ramesh Gowda", "9000012345@ybl", "SBIN0040123"),
    "rahul": ("Rahul Kumar", "rahul.k@okaxis", "UTIB0002345"),
    "priya": ("Priya Sharma", "9000023456@ybl", "HDFC0001122"),
    "arjun": ("Arjun Nair", "arjun.nair99@okhdfcbank", "HDFC0003344"),
    "sneha": ("Sneha Reddy", "9000034567@paytm", "PYTM0123456"),
    "karthik": ("Karthik Iyer", "karthik.iyer@oksbi", "SBIN0005566"),
    "ananya": ("Ananya Gupta", "9000045678@axl", "ICIC0007788"),
    "vikram": ("Vikram Singh", "vikramsingh@ibl", "IDIB000B123"),
    "meera": ("Meera Joshi", "9000056789@ybl", "KKBK0008899"),
}
FRIENDS = ("rahul", "priya", "arjun", "sneha", "karthik", "ananya", "vikram", "meera")
FRIEND_NOTES = ("dinner split", "auto", "movie", "thanks", "trip", "snacks")
MERCHANT_NOTES = ("Payment", "Paid via PhonePe", "UPI", "Pay to merchant")


def _txn(day: date, direction: str, amount: float, channel: str, name: str, **kw) -> dict:
    return {"date": day, "direction": direction, "amount": float(amount), "channel": channel,
            "name": name, "vpa": None, "ifsc": "SBIN0000000", "note": "UPI", "kind": "merchant",
            "display": name, "person": None, **kw}


def _month_txns(rng: random.Random, year: int, month: int) -> list[dict]:
    ndays = calendar.monthrange(year, month)[1]
    days = [date(year, month, d) for d in range(1, ndays + 1)]
    txns: list[dict] = []

    def person_txn(day, direction, amount, key, channel="UPI", note="UPI"):
        name, vpa, ifsc = PEOPLE[key]
        txns.append(_txn(day, direction, amount, channel, name, vpa=vpa, ifsc=ifsc,
                         note=note, kind="person", person=key))

    # income and fixed outgoings
    person_txn(days[0], "credit", 30000, "parent", channel="NEFT", note="ALLOWANCE")
    person_txn(days[14], "credit", rng.choice((2000, 3000)), "parent", channel="IMPS", note="extra")
    person_txn(days[4], "debit", 6000, "landlord", note="rent")
    for d, display, name, vpa, ifsc, amount in SUBSCRIPTIONS:
        txns.append(_txn(days[d - 1], "debit", amount, "UPI", name, vpa=vpa, ifsc=ifsc,
                         display=display, note="Mandate"))
    if (year, month) == (2026, 9):  # one big outlier for "unusual transactions"
        txns.append(_txn(days[11], "debit", 4999, "UPI", "AMAZON PAY", vpa="amazon@apl",
                         ifsc="UTIB0000100", display="Amazon", note="Payment"))

    # everyday merchant payments, weekends weighted per merchant
    for _ in range(rng.randint(170, 185)):
        display, name, vpa, ifsc, lo, hi, _w, boost = rng.choices(MERCHANTS, [m[6] for m in MERCHANTS])[0]
        day = rng.choices(days, [boost if d.weekday() >= 5 else 1.0 for d in days])[0]
        txns.append(_txn(day, "debit", rng.randint(lo, hi), "UPI", name, vpa=vpa, ifsc=ifsc,
                         display=display, note=rng.choice(MERCHANT_NOTES)))

    # friends: P2P both ways, plus one IMPS trip split
    for _ in range(rng.randint(10, 14)):
        person_txn(rng.choice(days), "debit", rng.randrange(50, 600, 10), rng.choice(FRIENDS),
                   note=rng.choice(FRIEND_NOTES))
    for _ in range(rng.randint(3, 5)):
        person_txn(rng.choice(days), "credit", rng.randrange(50, 400, 10), rng.choice(FRIENDS),
                   note=rng.choice(FRIEND_NOTES))
    person_txn(rng.choice(days[10:]), "debit", 1500, rng.choice(FRIENDS), channel="IMPS", note="trip")

    for _ in range(rng.randint(1, 2)):
        txns.append(_txn(rng.choice(days), "debit", rng.choice((500, 1000, 2000)), "ATM",
                         "KORAMANGALA BLR", display="ATM", kind="atm"))
    return txns


def generate(seed: int = SEED) -> list[dict]:
    """Ground-truth transactions in statement order, with running balance and refs."""
    rng = random.Random(seed)
    txns = [t for y, m in MONTHS for t in _month_txns(rng, y, m)]
    # credits first within a day so the allowance lands before that day's spending
    txns.sort(key=lambda t: (t["date"], t["direction"] != "credit"))

    out, balance, refs = [], OPENING_BALANCE, set()
    for t in txns:
        if t["direction"] == "debit" and t["amount"] > balance:
            continue  # skip rather than overdraw
        balance = round(balance + (t["amount"] if t["direction"] == "credit" else -t["amount"]), 2)
        ref = str(rng.randint(6_000_000_000_00, 6_999_999_999_99))
        while ref in refs:
            ref = str(rng.randint(6_000_000_000_00, 6_999_999_999_99))
        refs.add(ref)
        out.append({**t, "balance": balance, "ref": ref})
    return out


def narrate(t: dict, style: str) -> str:
    """Bank narration text. Style A ~ SBI (slashes), style B ~ HDFC (hyphens)."""
    name, ref, ifsc, note = t["name"].upper(), t["ref"], t["ifsc"], t["note"]
    drcr = "DR" if t["direction"] == "debit" else "CR"
    if t["channel"] == "UPI":
        if style == "A":
            return f"UPI/{drcr}/{ref}/{name[:20]}/{ifsc[:4]}/{t['vpa']}/{note}"
        return f"UPI-{name}-{t['vpa']}-{ifsc}-{ref}-{note.upper()}"
    if t["channel"] == "NEFT":
        utr = f"{ifsc[:4]}N{ref}"
        return f"NEFT/{drcr}/{utr}/{name}/{ifsc[:4]}" if style == "A" else f"NEFT {drcr}-{ifsc}-{name}-{utr}"
    if t["channel"] == "IMPS":
        return f"IMPS/P2A/{ref}/{name}/{note}" if style == "A" else f"IMPS-{ref}-{name}-{ifsc}-{note.upper()}"
    # ATM
    return f"ATM WDL/{ref[-6:]}/{name}" if style == "A" else f"NWD-{ref[-6:]}-SBIN0BLR-{name}"


def to_frame(txns: list[dict], style: str) -> pd.DataFrame:
    """Full-schema DataFrame: decoded + redacted ground truth, categories empty."""
    aliases: dict[str, str] = {}  # assigned in order of first appearance, like redact() will
    rows = []
    for t in txns:
        narration = narrate(t, style)
        counterparty, vpa, cp_type = t["display"], t["vpa"], "merchant"
        if t["kind"] == "person":
            alias = aliases.setdefault(t["person"], f"Person_{len(aliases) + 1:02d}")
            counterparty, cp_type = alias, "person"
            # only UPI narrations carry a VPA
            vpa = f"{alias.lower()}@{t['vpa'].split('@')[1]}" if t["vpa"] and t["channel"] == "UPI" else None
        elif t["kind"] == "atm":
            cp_type = "unknown"
        rows.append({
            "txn_id": make_txn_id(t["date"].isoformat(), t["amount"], t["direction"], narration),
            "date": t["date"].isoformat(), "narration": narration, "amount": t["amount"],
            "direction": t["direction"], "balance": t["balance"], "channel": t["channel"],
            "counterparty": counterparty, "vpa": vpa, "cp_type": cp_type,
            "category": None, "category_source": None,
        })
    return pd.DataFrame(rows, columns=list(COLUMNS))


def inr(x: float) -> str:
    """Indian digit grouping: 123456.78 -> '1,23,456.78'."""
    whole, frac = f"{x:.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join(([head] if head else []) + groups + [tail]) + "." + frac


def write_pdf(df: pd.DataFrame, path: Path, date_fmt: str, ruled: bool = True, column_boxes: bool = False) -> None:
    """Bank-like PDF: header block, opening/closing balance rows, wrapped narrations, footer.

    ruled=False draws no table lines, like many real bank PDFs (used by parser tests).
    column_boxes=True (with ruled=False) boxes each column but not the rows, like HDFC.
    """
    pdf = FPDF(format="A4")
    pdf.set_creation_date(datetime(2026, 10, 1, tzinfo=timezone.utc))  # fixed so output is byte-stable
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=15)

    def footer():
        pdf.set_y(-12)
        pdf.set_font("Helvetica", size=7)
        pdf.cell(0, 5, f"This is a computer generated statement. Page {pdf.page_no()} of {{nb}}", align="C")

    pdf.footer = footer
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 7, "SYNTHETIC BANK - ACCOUNT STATEMENT", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=9)
    for line in ("Account holder: TEST STUDENT", "Account no: XXXXXXXX4321",
                 "Branch: Koramangala, Bengaluru", "Period: 01/07/2026 to 30/09/2026"):
        pdf.cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    def fmt(d: str) -> str:
        return date.fromisoformat(d).strftime(date_fmt)

    pdf.set_font("Helvetica", size=8)
    with pdf.table(col_widths=(20, 90, 24, 24, 28),
                   text_align=("LEFT", "LEFT", "RIGHT", "RIGHT", "RIGHT"), v_align="TOP",
                   borders_layout="ALL" if ruled else "NONE") as table:
        header = table.row()
        for i, h in enumerate(("Date", "Narration", "Debit", "Credit", "Balance")):
            # HDFC centres its headers, so "Narration" starts right of where the narrations do
            header.cell(h, align="C" if column_boxes else None)
        table.row((fmt(df["date"].iloc[0]), "OPENING BALANCE", "", "", inr(OPENING_BALANCE)))
        for r in df.itertuples():
            debit = inr(r.amount) if r.direction == "debit" else ""
            credit = inr(r.amount) if r.direction == "credit" else ""
            table.row((fmt(r.date), r.narration, debit, credit, inr(r.balance)))
        table.row((fmt(df["date"].iloc[-1]), "CLOSING BALANCE", "", "", inr(df["balance"].iloc[-1])))
    if column_boxes:
        widths = [w * pdf.epw / 186 for w in (20, 90, 24, 24, 28)]  # same scaling fpdf applies to col_widths
        for p in range(1, pdf.pages_count + 1):
            pdf.page = p
            top = 40 if p == 1 else pdf.t_margin
            x = pdf.l_margin
            for w in widths:
                pdf.rect(x, top, w, pdf.h - 15 - top)
                x += w
    pdf.output(str(path))


def main(out_dir: Path = OUT_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    txns = generate()
    for style, stem, date_fmt in (("A", "statement", "%d/%m/%y"), ("B", "statement_b", "%d-%b-%Y")):
        df = to_frame(txns, style)
        df.to_csv(out_dir / f"{stem}.csv", index=False)
        write_pdf(df, out_dir / f"{stem}.pdf", date_fmt)
    per_month = df.assign(m=df["date"].str[:7]).groupby(["m", "channel"]).size().unstack(fill_value=0)
    print(per_month.to_string())
    print(f"{len(df)} rows, closing balance {inr(df['balance'].iloc[-1])}; wrote {out_dir}")


if __name__ == "__main__":
    main()
