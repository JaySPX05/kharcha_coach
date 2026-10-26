"""Fixed category list + deterministic rules that run before any model call."""
from __future__ import annotations

import re

from core.schema import CATEGORIES  # noqa: F401  (re-exported; core/schema.py is the one list)

_SUFFIXES = re.compile(
    r"\b(pvt|private|ltd|limited|llp|india|technologies|technology|tech|services|"
    r"payments?|retail|online|store|co|inc)\b"
)


def normalise_merchant(name: str | None) -> str:
    """'Swiggy Pvt Ltd' / 'SWIGGY' / 'swiggy.' -> 'swiggy'. Used as the cache key."""
    s = name.lower() if isinstance(name, str) else ""
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = _SUFFIXES.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


# keyword (matched against normalised counterparty + VPA handle) -> category.
# Order matters: first hit wins, so put specific words before generic ones.
KEYWORD_RULES: list[tuple[str, str]] = [
    # food delivery / quick commerce
    ("swiggy instamart", "Groceries"), ("instamart", "Groceries"),
    ("swiggy", "Food delivery"), ("zomato", "Food delivery"), ("eatsure", "Food delivery"),
    ("zepto", "Groceries"), ("blinkit", "Groceries"), ("bigbasket", "Groceries"),
    ("dmart", "Groceries"), ("jiomart", "Groceries"), ("kirana", "Groceries"), ("provision", "Groceries"), ("general stores", "Groceries"), ("milk", "Groceries"), ("supermarket", "Groceries"), ("country delight", "Groceries"), ("dunzo", "Groceries"),
    ("ratnadeep", "Groceries"), ("more supermarket", "Groceries"),
    # transport
    ("rapido", "Transport"), ("uber", "Transport"), ("ola", "Transport"), ("bmtc", "Transport"), ("ksrtc", "Travel"),
    ("namma metro", "Transport"), ("bmrcl", "Transport"), ("metro", "Transport"),
    ("bmtc", "Transport"), ("yulu", "Transport"), ("bounce", "Transport"),
    ("indian oil", "Fuel"), ("iocl", "Fuel"), ("bharat petroleum", "Fuel"),
    ("bpcl", "Fuel"), ("hpcl", "Fuel"), ("petrol", "Fuel"), ("shell", "Fuel"),
    # shopping
    ("amazon", "Shopping"), ("flipkart", "Shopping"), ("myntra", "Shopping"),
    ("ajio", "Shopping"), ("meesho", "Shopping"), ("nykaa", "Shopping"),
    ("decathlon", "Shopping"), ("croma", "Shopping"),
    # subscriptions
    ("spotify", "Subscriptions"), ("netflix", "Subscriptions"),
    ("hotstar", "Subscriptions"), ("jiohotstar", "Subscriptions"), ("premium", "Subscriptions"), ("prime video", "Subscriptions"),
    ("youtube", "Subscriptions"), ("google one", "Subscriptions"),
    ("apple", "Subscriptions"), ("chatgpt", "Subscriptions"), ("openai", "Subscriptions"),
    # bills
    ("airtel", "Bills & recharge"), ("jio", "Bills & recharge"), ("vodafone", "Bills & recharge"),
    ("bescom", "Bills & recharge"), ("bwssb", "Bills & recharge"), ("act fibernet", "Bills & recharge"),
    ("recharge", "Bills & recharge"), ("electricity", "Bills & recharge"),
    # eating out
    ("starbucks", "Eating out"), ("chai", "Eating out"), ("cafe", "Eating out"),
    ("canteen", "Eating out"), ("darshini", "Eating out"), ("restaurant", "Eating out"),
    ("bakery", "Eating out"), ("coffee", "Eating out"), ("bhavan", "Eating out"), ("foods", "Eating out"), ("pizza", "Eating out"), ("darshini", "Eating out"), ("tea stall", "Eating out"), ("dominos", "Eating out"), ("mcdonald", "Eating out"),
    ("kfc", "Eating out"), ("tea", "Eating out"), ("juice", "Eating out"),
    # rent / education / health
    ("rent", "Rent"), ("hostel", "Rent"), ("stanza", "Rent"), ("zolo", "Rent"), ("colive", "Rent"), ("pg ", "Rent"), ("nestaway", "Rent"),
    ("college", "Education"), ("university", "Education"), ("fees", "Education"), ("fee", "Education"), ("unacademy", "Education"), ("nptel", "Education"),
    ("udemy", "Education"), ("coursera", "Education"),
    ("apollo", "Health"), ("pharmeasy", "Health"), ("1mg", "Health"),
    ("medplus", "Health"), ("pharmacy", "Health"), ("hospital", "Health"),
    ("clinic", "Health"), ("cult fit", "Health"), ("cultfit", "Health"),
    # entertainment / travel
    ("bookmyshow", "Entertainment"), ("pvr", "Entertainment"), ("inox", "Entertainment"),
    ("district", "Entertainment"), ("steam", "Entertainment"),
    ("irctc", "Travel"), ("makemytrip", "Travel"), ("goibibo", "Travel"),
    ("redbus", "Travel"), ("indigo", "Travel"), ("cleartrip", "Travel"),
    # investments
    ("zerodha", "Investments"), ("groww", "Investments"), ("upstox", "Investments"),
    ("kuvera", "Investments"), ("mutual fund", "Investments"), ("sip", "Investments"),
]


def rule_category(counterparty: str | None, vpa: str | None = None) -> str | None:
    """Return a category if a keyword rule matches, else None."""
    handle = vpa.split("@")[0] if isinstance(vpa, str) else ""
    hay = f" {normalise_merchant(counterparty)} {normalise_merchant(handle)} "
    for kw, cat in KEYWORD_RULES:
        # word-boundary match so 'ola' does not hit 'cola' and 'tea' not 'steam'
        if re.search(rf"(?<![a-z0-9]){re.escape(kw.strip())}(?![a-z0-9])", hay):
            return cat
    return None
