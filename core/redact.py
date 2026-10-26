"""Mask PII before anything leaves core/. Runs after decode_upi()."""

import re

import pandas as pd

LONG_DIGITS = re.compile(r"\d{10,}")  # phones (10), UPI refs (12), account numbers (11-18)
ALIASED_CHANNELS = ("UPI", "NEFT", "IMPS", "OTHER")  # OTHER keeps raw text ("CHQ DEP-RAHUL SHARMA")


def _mask_digits(text: object) -> object:
    """'412345678901' -> 'XXXXXXXX8901'. Non-strings (None/NaN) pass through."""
    if not isinstance(text, str):
        return text
    return LONG_DIGITS.sub(lambda m: "X" * (len(m.group()) - 4) + m.group()[-4:], text)


def redact(df: pd.DataFrame) -> pd.DataFrame:
    """People -> stable Person_NN aliases (first appearance order); long digit runs -> last 4.

    Merchant names and VPAs stay readable. Unknown counterparties on UPI/NEFT/IMPS/OTHER are
    aliased too, since they might be people.
    """
    out = df.copy()
    aliases: dict[str, str] = {}
    is_person = (out["cp_type"] == "person") | (
        (out["cp_type"] == "unknown") & out["channel"].isin(ALIASED_CHANNELS)
    )
    for i in out.index[is_person]:
        name, vpa, narration = out.at[i, "counterparty"], out.at[i, "vpa"], out.at[i, "narration"]
        key = "".join(str(name or vpa).upper().split())  # spaceless: PDF wraps can glue name parts
        alias = aliases.setdefault(key, f"Person_{len(aliases) + 1:02d}")
        if isinstance(vpa, str):
            new_vpa = f"{alias.lower()}@{vpa.partition('@')[2]}"
            narration = narration.replace(vpa, new_vpa)
            out.at[i, "vpa"] = new_vpa
        if isinstance(name, str) and name:
            # optional spaces between words: the narration may hold a glued "KARTHIKIYER"
            pattern = r"\s*".join(re.escape(w) for w in name.split())
            narration = re.sub(pattern, alias, narration, flags=re.I)
        out.at[i, "narration"] = narration
        out.at[i, "counterparty"] = alias
    for col in ("narration", "counterparty", "vpa"):
        out[col] = out[col].map(_mask_digits)
    return out
