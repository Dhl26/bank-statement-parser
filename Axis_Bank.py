import streamlit as st
import pdfplumber
import pandas as pd
from collections import Counter
import re


# ------------------------------------------------------
# Account Details Extractor
# ------------------------------------------------------
def extract_axis_account_details(text: str) -> dict:
    """Pulls basic account info from Axis PDF header text."""
    details = {}

    # Name & address
    name_match = re.search(r"^([A-Z\s]+)\n", text, re.MULTILINE)
    details["Account Holder"] = name_match.group(1).strip() if name_match else "N/A"

    # Address lines (simple search for Bengaluru/Karnataka block)
    addr_match = re.findall(r"(?i)([0-9]+.*BANGALORE|BENGALURU|KARNATAKA|560\d+)", text)
    details["Address"] = " ".join(addr_match) if addr_match else "N/A"

    cust_no = re.search(r"Customer\s*No\s*:\s*(\d+)", text)
    details["Customer No"] = cust_no.group(1) if cust_no else "N/A"

    scheme = re.search(r"Scheme\s*:\s*([\w\-]+)", text)
    details["Scheme"] = scheme.group(1) if scheme else "N/A"

    currency = re.search(r"Currency\s*:\s*([A-Z]+)", text)
    details["Currency"] = currency.group(1) if currency else "N/A"

    acc_no = re.search(r"Statement of Account No\s*:\s*(\d+)", text)
    details["Account No"] = acc_no.group(1) if acc_no else "N/A"

    return details


# ------------------------------------------------------
# Transaction Extractor
# ------------------------------------------------------
def extract_axis_transactions(pdf) -> pd.DataFrame:
    rows = []

    for page in pdf.pages:
        try:
            table = page.extract_table()
            if not table:
                continue

            # First row = headers
            headers = [h.strip() if h else "" for h in table[0]]

            for row in table[1:]:
                if not row:
                    continue

                record = dict(zip(headers, row))

                # Handle Opening Balance
                if record.get("Particulars") and "OPENING BALANCE" in record["Particulars"]:
                    rows.append({
                        "Tran Date": "",
                        "Chq No": "",
                        "Particulars": "OPENING BALANCE",
                        "Debit": 0,
                        "Credit": 0,
                        "Balance": (record.get("Balance") or "0").replace(",", ""),
                        "Init. Br": record.get("Init. Br") or "N/A"
                    })
                else:
                    rows.append({
                        "Tran Date": record.get("Tran Date") or "",
                        "Chq No": record.get("Chq No") or "",
                        "Particulars": record.get("Particulars") or "",
                        "Debit": (record.get("Debit") or "0").replace(",", ""),
                        "Credit": (record.get("Credit") or "0").replace(",", ""),
                        "Balance": (record.get("Balance") or "0").replace(",", ""),
                        "Init. Br": record.get("Init. Br") or "N/A"
                    })

        except Exception as e:
            print("Error extracting table:", e)

    return pd.DataFrame(rows)


# ------------------------------------------------------
# Frequency Table
# ------------------------------------------------------
def build_frequency_table(df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    freq = Counter(df["Particulars"])
    return pd.DataFrame(freq.most_common(top_n), columns=["Particulars", "Count"])


# ------------------------------------------------------
# Streamlit App
# ------------------------------------------------------
def axis_parser():
    st.set_page_config(page_title="Axis Bank Statement Parser", layout="wide")
    st.title("🏦 Axis Bank Statement Parser")

    uploaded = st.file_uploader("Upload Axis Bank Statement (PDF)", type=["pdf"])

    if uploaded:
        with pdfplumber.open(uploaded) as pdf:
            all_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
            txns = extract_axis_transactions(pdf)

        # 1. Account details
        st.subheader("📋 Account Details")
        acct = extract_axis_account_details(all_text)
        st.table(pd.DataFrame(acct.items(), columns=["Field", "Value"]))

        # 2. Transactions
        st.subheader("💰 Transactions")
        if not txns.empty:
            display_cols = ["Tran Date", "Chq No", "Particulars", "Debit", "Credit", "Balance", "Init. Br"]
            st.dataframe(txns[display_cols], use_container_width=True)
        else:
            st.warning("No transactions matched – try another statement or tweak extraction.")

        # 3. Frequency
        st.subheader("📊 Frequent Transactions")
        freq = build_frequency_table(txns, 10)
        if not freq.empty:
            st.table(freq)
        else:
            st.info("No frequent transaction data available.")


# ------------------------------------------------------
# Main entry point
# ------------------------------------------------------
def main():
    axis_parser()


if __name__ == "__main__":
    main()
