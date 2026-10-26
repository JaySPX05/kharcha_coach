import pandas as pd
import pytest

from core.upi import decode_narration, decode_upi

CASES = [
    # style A (SBI-like)
    ("UPI/DR/412345678901/SWIGGY/YESB/swiggy@ybl/Payment", "UPI", "Swiggy", "swiggy@ybl", "merchant"),
    ("UPI/DR/412345678901/RELIANCE JIO/YESB/jiorecharge@ybl/Mandate", "UPI", "Jio Recharge", "jiorecharge@ybl", "merchant"),
    ("UPI/DR/412345678901/SRI LAKSHMI TEA STAL/YESB/Q648213759@ybl/Payment", "UPI", "Sri Lakshmi Tea Stal", "Q648213759@ybl", "merchant"),
    ("UPI/DR/412345678901/PESCANTEEN/UTIB/pescanteen@okaxis/UPI", "UPI", "Pescanteen", "pescanteen@okaxis", "merchant"),
    ("UPI/DR/412345678901/RAHUL KUMAR/UTIB/rahul.k@okaxis/dinner split", "UPI", "Rahul Kumar", "rahul.k@okaxis", "person"),
    ("UPI/CR/412345678901/PRIYA SHARMA/HDFC/9000023456@ybl/thanks", "UPI", "Priya Sharma", "9000023456@ybl", "person"),
    ("NEFT/CR/CNRBN612345678901/SURESH RAO/CNRB", "NEFT", "Suresh Rao", None, "person"),
    ("IMPS/P2A/612345678901/ARJUN NAIR/trip", "IMPS", "Arjun Nair", None, "person"),
    ("ATM WDL/123456/KORAMANGALA BLR", "ATM", "ATM", None, "unknown"),
    # style B (HDFC-like)
    ("UPI-SWIGGY-swiggy@ybl-YESB0YBLUPI-412345678901-PAYMENT", "UPI", "Swiggy", "swiggy@ybl", "merchant"),
    ("UPI-BMRCL NAMMA METRO-nammametro.bmrcl@sbi-SBIN0000813-412345678901-UPI", "UPI", "Namma Metro", "nammametro.bmrcl@sbi", "merchant"),
    ("UPI-BHAIYA CHAI CORNER-paytmqr5kq2m8@paytm-PYTM0123456-412345678901-PAY TO MERCHANT", "UPI", "Bhaiya Chai Corner", "paytmqr5kq2m8@paytm", "merchant"),
    ("UPI-SNEHA REDDY-9000034567@paytm-PYTM0123456-412345678901-MOVIE", "UPI", "Sneha Reddy", "9000034567@paytm", "person"),
    ("UPI-VIKRAM SINGH-vikramsingh@ibl-IDIB000B123-412345678901-AUTO", "UPI", "Vikram Singh", "vikramsingh@ibl", "person"),
    ("NEFT CR-CNRB0001234-SURESH RAO-CNRBN612345678901", "NEFT", "Suresh Rao", None, "person"),
    ("IMPS-612345678901-MEERA JOSHI-KKBK0008899-TRIP", "IMPS", "Meera Joshi", None, "person"),
    ("NWD-123456-SBIN0BLR-KORAMANGALA BLR", "ATM", "ATM", None, "unknown"),
    # HDFC shapes seen on a real statement: Paytm shop QR with an owner's name, autopay mandates, Razorpay
    ("UPI-RAMESH KUMAR-paytm.s1abc2d@pty-YESB0PTMUPI-412345678901-UPI", "UPI", "Ramesh Kumar", "paytm.s1abc2d@pty", "merchant"),
    ("UPI-AUTOPAY-SKILLSHARE IN-skillshare@icici-ICIC0000001-412345678901-MANDATE", "UPI", "Autopay-Skillshare In", "skillshare@icici", "merchant"),
    ("UPI-ANAND BOOK HOUSE-anandbook.rzp@axisbank-UTIB0000100-412345678901-UPI", "UPI", "Anand Book House", "anandbook.rzp@axisbank", "merchant"),
    # other shapes the decoder must not choke on
    ("UPI-SHARMA GENERAL STORE-9000099999@ybl-SBIN0000001-412345678901-PAY", "UPI", "Sharma General Store", "9000099999@ybl", "merchant"),
    ("UPI-MARTIN DSOUZA-martin.d@okicici-ICIC0000001-412345678901-PAY", "UPI", "Martin Dsouza", "martin.d@okicici", "person"),
    ("UPI-GPAY MERCHANT-gpay-11234@okbizaxis-UTIB0000001-412345678901-PAY", "UPI", "Gpay Merchant", "gpay-11234@okbizaxis", "merchant"),
    ("UPI/412345678901/Paid to/raju.k@okicici/ICICI Bank", "UPI", "raju.k", "raju.k@okicici", "unknown"),
    ("POS 4512XXXXXXXX1234 DMART BLR", "CARD", "POS 4512XXXXXXXX1234 DMART BLR", None, "unknown"),
    ("INTEREST CREDIT", "OTHER", "INTEREST CREDIT", None, "unknown"),
]


@pytest.mark.parametrize("narration, channel, counterparty, vpa, cp_type", CASES)
def test_decode_narration(narration, channel, counterparty, vpa, cp_type):
    assert decode_narration(narration) == {
        "channel": channel, "counterparty": counterparty, "vpa": vpa, "cp_type": cp_type,
    }


def test_samples_decode_to_ground_truth(sample):
    truth, _, decoded, _ = sample
    assert (decoded["channel"].values == truth["channel"].values).all()
    assert (decoded["cp_type"].values == truth["cp_type"].values).all()
    merchants = truth["cp_type"] == "merchant"
    assert (decoded["vpa"][merchants].values == truth["vpa"][merchants].values).all()
    assert (decoded["channel"] != "OTHER").all()


def test_one_display_name_per_vpa():
    df = pd.DataFrame({"narration": [
        "UPI/DR/412345678901/PESCANTEEN/UTIB/pescanteen@okaxis/UPI",
        "UPI/DR/412345678902/PES CANTEEN/UTIB/pescanteen@okaxis/UPI",
    ]})
    assert decode_upi(df)["counterparty"].tolist() == ["Pes Canteen", "Pes Canteen"]
