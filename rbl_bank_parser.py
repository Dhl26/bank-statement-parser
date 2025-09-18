import streamlit as st
import pdfplumber
import pandas as pd
import re
from collections import Counter

def rbl_parser():

    def extract_rbl_account_details(text: str) -> dict:
        details = {}
        patterns = {
            "Accountholder Name": r"Accountholder Name\s*:\s*(.+)",
            "Customer Address": r"Customer Address\s*:\s*(.+)",
            "Phone": r"Phone\s*:\s*([+\d\(\)\s-]+)",
            "Email Id": r"Email Id\s*:\s*([\w\.-]+@[\w\.-]+)",
            "CIF ID": r"CIF ID\s*:\s*(\d+)",
            "A/c Currency": r"A/c Currency\s*:\s*([A-Z]+)",
            "A/c Open Date": r"A/c Open Date\s*:\s*(.+)",
            "A/c Type": r"A/c Type\s*:\s*(.+)",
            "A/c Status": r"A/c Status\s*:\s*(.+)",
            "Home Branch": r"Home Branch\s*:\s*(.+)",
            "Home Branch Address": r"Home Branch Address\s*:\s*(.+)",
            "IFSC/RTGS/NEFT": r"IFSC/RTGS/NEFT\s*:\s*([A-Z0-9]+)",
            "MICR Code": r"MICR Code\s*:\s*(\d+)",
            "ECS A/c No": r"ECS A/c No\s*:\s*(\d+)",
            "Statement Period": r"Period\s*:\s*(.+)"
        }
        for field, pattern in patterns.items():
            m = re.search(pattern, text, re.IGNORECASE)
            details[field] = m.group(1).strip() if m else "N/A"
        return details


    # ---------------------------
    # Transactions Extractor
    # ---------------------------
    DATE_RE = r"\d{2}-[A-Za-z]{3}-\d{4}"


    def extract_rbl_transactions(text: str) -> pd.DataFrame:
        rows = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue

            m = re.match(rf"^({DATE_RE})\s+(.*)$", line)
            if not m:
                continue

            tran_date = m.group(1)
            rest = m.group(2)

            # find Value Date
            val_date_match = re.search(DATE_RE, rest)
            if val_date_match:
                value_date = val_date_match.group(0)
                desc = rest[:val_date_match.start()].strip()
                tail = rest[val_date_match.end():].strip()
            else:
                value_date, desc, tail = "", rest, ""

            # capture last number as Balance
            nums = re.findall(r"[\d,]+\.\d{2}", tail)
            balance = float(nums[-1].replace(",", "")) if nums else 0.0

            rows.append({
                "Date": tran_date,
                "Transaction Details": desc,
                "Value Date": value_date,
                "Balance Amt": balance
            })

        df = pd.DataFrame(rows)

        if df.empty:
            return df

        # infer withdrawals/deposits from balance differences
        df["Withdrawal Amt"] = 0.0
        df["Deposit Amt"] = 0.0

        prev_balance = None
        for i in range(len(df)):
            bal = df.loc[i, "Balance Amt"]
            if prev_balance is not None:
                if bal > prev_balance:
                    df.loc[i, "Deposit Amt"] = bal - prev_balance
                elif bal < prev_balance:
                    df.loc[i, "Withdrawal Amt"] = prev_balance - bal
            prev_balance = bal

        # convert dates and drop time part
        try:
            df["Date"] = pd.to_datetime(df["Date"], format="%d-%b-%Y", errors="coerce").dt.date
            df["Value Date"] = pd.to_datetime(df["Value Date"], format="%d-%b-%Y", errors="coerce").dt.date
        except Exception:
            pass

        # reorder columns → Balance last
        df = df[["Date", "Transaction Details", "Value Date", "Withdrawal Amt", "Deposit Amt", "Balance Amt"]]

        return df


    # ---------------------------
    # Frequency
    # ---------------------------
    def get_frequent_transactions(df: pd.DataFrame, top_n=10):
        if df.empty:
            return pd.DataFrame()
        freq = Counter(df["Transaction Details"].astype(str))
        return pd.DataFrame(freq.most_common(top_n), columns=["Transaction Details", "Count"])


    # ---------------------------
    # Wrapper for Streamlit UI
    # ---------------------------
    def main():
        st.set_page_config(page_title="RBL Bank Statement Parser", layout="wide")
        st.title("🏦 RBL Bank Statement Parser")

        uploaded_file = st.file_uploader("Upload RBL Bank Statement PDF (text-based)", type=["pdf"])

        if uploaded_file:
            with pdfplumber.open(uploaded_file) as pdf:
                all_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

            # Account details
            st.subheader("📋 Account Details")
            acct = extract_rbl_account_details(all_text)
            st.table(pd.DataFrame(acct.items(), columns=["Field", "Value"]))

            # Transactions
            st.subheader("💰 Transactions")
            txns = extract_rbl_transactions(all_text)

            if not txns.empty:
                st.dataframe(txns, use_container_width=True)

                # Frequency
                st.subheader("📊 Frequent Transactions ")
                freq = get_frequent_transactions(txns)
                if not freq.empty:
                    st.table(freq)
                else:
                    st.info("No frequent transaction data available.")
            else:
                st.warning("⚠️ No transactions matched. If this persists, please enable debug to see raw lines.")


  
    main()


if __name__ == "__main__":
    rbl_parser()

