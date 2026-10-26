"""Decode bank narrations into channel, counterparty, vpa and cp_type. Local only, no models."""

import re

import pandas as pd

# VPA = handle@psp, e.g. swiggy@ybl, rahul.k@okaxis, 9000012345@paytm
VPA = r"[A-Za-z0-9._-]+@[A-Za-z]+"
IFSC = r"[A-Z]{4}0[A-Z0-9]{6}"

# Each pattern captures what it can: name, vpa, ref. Searched in order; first hit wins.
PATTERNS = {
    "UPI": (
        # SBI-like:  UPI/DR/412345678901/SWIGGY/YESB/swiggy@ybl/Payment
        re.compile(rf"\bUPI/(?:DR|CR)/(?P<ref>\d{{12}})/(?P<name>[^/]*)/(?P<bank>[A-Z]{{4}})/(?P<vpa>{VPA})", re.I),
        # HDFC-like: UPI-SWIGGY-swiggy@ybl-YESB0YBLUPI-412345678901-PAYMENT
        re.compile(rf"\bUPI-(?P<name>.*?)-(?P<vpa>{VPA})-(?P<ifsc>{IFSC})-(?P<ref>\d{{12}})", re.I),
        # fallback for other banks: any VPA after the UPI marker, no name
        re.compile(rf"\bUPI\b.*?(?P<vpa>{VPA})", re.I),
    ),
    "NEFT": (
        re.compile(r"\bNEFT/(?:DR|CR)/(?P<ref>[A-Z0-9]+)/(?P<name>[^/]+)", re.I),
        re.compile(rf"\bNEFT (?:DR|CR)-(?P<ifsc>{IFSC})-(?P<name>[^-]+)-", re.I),
    ),
    "IMPS": (
        re.compile(r"\bIMPS/P2[AM]/(?P<ref>\d+)/(?P<name>[^/]+)", re.I),
        re.compile(r"\bIMPS-(?P<ref>\d+)-(?P<name>[^-]+)-", re.I),
    ),
}
CHANNEL_PREFIX = (
    ("UPI", re.compile(r"\bUPI[/-]", re.I)),
    ("NEFT", re.compile(r"\bNEFT\b", re.I)),
    ("IMPS", re.compile(r"\bIMPS\b", re.I)),
    ("ATM", re.compile(r"^(ATM WDL|ATW|NWD|ATM CASH|CASH WDL)", re.I)),
    ("CARD", re.compile(r"^(POS|ECOM|CARD)\b", re.I)),
)

# keyword (matched at the start of the VPA handle or of a name word) -> display name
KNOWN_MERCHANTS = {
    "instamart": "Swiggy Instamart", "swiggy": "Swiggy", "zomato": "Zomato", "zepto": "Zepto",
    "blinkit": "Blinkit", "bigbasket": "BigBasket", "dunzo": "Dunzo",
    "rapido": "Rapido", "uber": "Uber", "olacabs": "Ola", "nammametro": "Namma Metro",
    "bmrcl": "Namma Metro", "irctc": "IRCTC", "redbus": "redBus",
    "chaipoint": "Chai Point", "starbucks": "Starbucks", "dominos": "Domino's", "mcdonalds": "McDonald's",
    "amazon": "Amazon", "flipkart": "Flipkart", "myntra": "Myntra", "ajio": "AJIO", "meesho": "Meesho",
    "nykaa": "Nykaa", "spotify": "Spotify", "netflix": "Netflix", "hotstar": "Disney+ Hotstar",
    "jio": "Jio Recharge", "airtel": "Airtel", "bescom": "BESCOM", "bookmyshow": "BookMyShow", "pvr": "PVR",
}
MERCHANT_WORDS = frozenset("""
    STORE STORES MART SUPERMARKET TEA CHAI CAFE COFFEE CANTEEN HOTEL RESTAURANT BHAVAN DARSHINI STALL
    BAKERY BAKERS SWEETS FOODS FOOD KIRANA GENERAL CORNER ENTERPRISES ENTERPRISE TRADERS AGENCIES PVT LTD
    LIMITED PRIVATE MEDICAL MEDICALS PHARMACY CHEMIST CLINIC HOSPITAL SERVICES STATION PETROL FUELS FUEL
    MOTORS INDIA TECHNOLOGIES SOLUTIONS CENTRE CENTER SALON HOSTEL MESS JUICE XEROX STATIONERY BOOKS
    ELECTRONICS MOBILES TEXTILES FASHION MARKET MARKETPLACE PAYMENTS RETAIL COLLEGE UNIVERSITY SCHOOL
    AUTOPAY MANDATE
""".split())
PHONE_HANDLE = re.compile(r"^(?:\+?91)?[6-9]\d{9}$")  # Indian mobile, optional 91 prefix
MERCHANT_HANDLE = re.compile(r"^(paytmqr|paytm\.|q\d{6,}|bharatpe|gpay-|razorpay|cf\.)|merchant|\.payu|\.rzp$", re.I)
NAME_HANDLE = re.compile(r"^[a-z][a-z0-9._]*$", re.I)


def _known(handle: str, name: str) -> str | None:
    words = name.lower().split()
    for key, display in KNOWN_MERCHANTS.items():
        if handle.lower().startswith(key) or any(w.startswith(key) for w in words):
            return display
    return None


def _has_merchant_word(name: str) -> bool:
    words = name.upper().split()
    if any(w in MERCHANT_WORDS for w in words):
        return True
    # PDF wrapping can glue words ("PESCANTEEN"); only long keywords are safe as substrings (MART ⊂ MARTIN)
    squashed = "".join(words)
    return any(len(k) >= 6 and k in squashed for k in MERCHANT_WORDS)


def _cp_type(name: str, handle: str, psp: str) -> str:
    words = name.upper().split()
    if _has_merchant_word(name) or MERCHANT_HANDLE.search(handle) or "biz" in psp.lower():
        return "merchant"
    if PHONE_HANDLE.match(handle):
        return "person"
    looks_human = 1 <= len(words) <= 4 and all(w.isalpha() for w in words)
    if looks_human and (not handle or NAME_HANDLE.match(handle)):
        return "person"
    return "unknown"


def decode_narration(narration: str) -> dict:
    """One narration -> {channel, counterparty, vpa, cp_type}. Raw values; redact() masks PII later."""
    text = " ".join(str(narration or "").split())
    channel = next((ch for ch, rx in CHANNEL_PREFIX if rx.search(text)), "OTHER")
    if channel == "ATM":
        return {"channel": "ATM", "counterparty": "ATM", "vpa": None, "cp_type": "unknown"}

    fields: dict = {}
    for rx in PATTERNS.get(channel, ()):
        m = rx.search(text)
        if m:
            fields = {k: v for k, v in m.groupdict().items() if v}
            break
    name = " ".join(fields.get("name", "").split())
    vpa = fields.get("vpa")
    handle, _, psp = (vpa or "").partition("@")

    known = _known(handle, name)
    if known:
        return {"channel": channel, "counterparty": known, "vpa": vpa, "cp_type": "merchant"}
    if channel == "OTHER" or not (name or handle):
        return {"channel": channel, "counterparty": text[:40] or "Unknown", "vpa": vpa, "cp_type": "unknown"}
    return {"channel": channel, "counterparty": name.title() if name else handle,
            "vpa": vpa, "cp_type": _cp_type(name, handle, psp)}


def decode_upi(df: pd.DataFrame) -> pd.DataFrame:
    """Fill channel, counterparty, vpa, cp_type from each narration."""
    out = df.copy()
    decoded = pd.DataFrame([decode_narration(n) for n in out["narration"]], index=out.index)
    # one display name per VPA: PDF wraps can glue words, so prefer the variant with the most spaces
    names = decoded.dropna(subset=["vpa"]).groupby("vpa")["counterparty"]
    best = names.agg(lambda s: max(s, key=lambda n: (n.count(" "), len(n))))
    decoded["counterparty"] = decoded["vpa"].map(best).astype(object).fillna(decoded["counterparty"])
    out[decoded.columns] = decoded.astype(object)
    return out
