import streamlit as st
import pdfplumber
import pandas as pd
import re
import os
from io import BytesIO
from collections import Counter

def run_pdf_parser_iob():
    # === CONFIG ===
    DEFAULT_FILE = "iob stmt.pdf"


    def extract_metadata_from_pdf(file):
        metadata = {}
        lines = []

        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    lines.extend([l.strip() for l in text.split("\n") if l.strip()])
                break  # only need first page

        full_text = "\n".join(lines)

        # --- Bank ---
        metadata["Bank"] = "INDIAN OVERSEAS BANK"

        # --- Branch + Address ---
        branch_line = next((ln for ln in lines if "INDIAN OVERSEAS BANK" in ln.upper()), "")
        if branch_line:
            # Example: "INDIAN OVERSEAS BANK, MAHALAKSHMIPURAM, BANGALORE"
            branch_line = re.sub(r"\s*Page\s*\d+\s*$", "", branch_line, flags=re.I).strip()
            parts = branch_line.split(",", 1)
            if len(parts) == 2:
                branch_info = parts[1].strip()
                metadata["Branch"] = branch_info.split(",")[0].strip()
                metadata["Branch Address"] = branch_info
            else:
                metadata["Branch"] = ""
                metadata["Branch Address"] = branch_line.strip()

        # --- Account Number + Holder Name ---
        acct_line = next((ln for ln in lines if "Account Number" in ln), "")
        if acct_line:
            # Example: "Account Number :2314569874512563/INR Jhone Doe"
            match = re.search(r"Account Number\s*:\s*([\d]+)/(INR)\s+(.*)", acct_line, re.I)
            if match:
                metadata["Account Number"] = match.group(1)
                metadata["Product"] = match.group(2)
                metadata["Account Holder Name"] = match.group(3).strip()

        # --- Report To ---
        rpt_match = re.search(r"Report\s*To\s*:\s*(\w+)", full_text, re.I)
        metadata["Report To"] = rpt_match.group(1) if rpt_match else ""

        # --- Service Outlet ---
        svc_match = re.search(r"Service\s*OutLet\s*:\s*([\w\s]+)", full_text, re.I)
        metadata["Service Outlet"] = svc_match.group(1).strip() if svc_match else ""

        # --- Statement Period ---
        stmt_period = re.search(
            r"Report\s*for\s*the\s*Period\s*:\s*(\d{2}-\d{2}-\d{4})\s*TO\s*(\d{2}-\d{2}-\d{4})",
            full_text,
            re.I
        )
        metadata["Statement Period"] = (
            f"{stmt_period.group(1)} to {stmt_period.group(2)}" if stmt_period else ""
        )

       

        return metadata


     
 


    def parse_amount(value):
        if value is None:
            return None
        s = str(value).strip()
        if s == "" or s == "-" or s.upper() in ["NA", "N/A", "—", "–"]:
            return None
        s_up = s.upper().replace("CR", "").replace("DR", "")
        if "(" in s_up and ")" in s_up:
            s_up = s_up.replace("(", "-").replace(")", "")
        s_clean = re.sub(r"[^\d\.-]", "", s_up)
        if s_clean in ["", "-", "."]:
            return None
        try:
            return float(s_clean)
        except Exception:
            return None


    def split_date_tran(s):
        """
        Split combined Post Date + Tran like '16-04-2019S42347939'
        Returns: date_str, tran_str
        """
        match = re.match(r"(\d{2}-\d{2}-\d{4})(.*)", s)
        if match:
            return match.group(1), match.group(2) if match.group(2) else None
        return None, s


    def parse_transaction_line(parts):
        """
        Parse a transaction line into structured fields
        """

        # 1. Post date + Tran
        post_date, tran = split_date_tran(parts[0])

        # 2. Ref number (next token if available)
        ref_num = parts[1] if len(parts) > 1 else None

        # 3. Last = Balance (with CR/DR)
        balance_raw = parts[-1]
        balance = parse_amount(balance_raw)
        balance_type = "CR" if "CR" in balance_raw.upper() else "DR"

        # 4. Second last = Transaction amount
        amount_raw = parts[-2]
        amount = parse_amount(amount_raw)

        debit, credit = None, None
        if amount is not None:
            if balance_type == "CR":
                credit = amount
            else:
                debit = amount

        # 5. Particulars = everything between ref_num and amount
        particulars = " ".join(parts[2:-2]).strip() if len(parts) > 4 else None

        return {
            "Post Date": post_date,
            "Tran": tran,
            "Ref Num": ref_num,
            "Particulars": particulars,
            "Debit": debit,
            "Credit": credit,
            "Balance": balance
        }


    def parse_iob_pdf(file_path):
        rows = []
        start_parsing = False  # <-- flag to start only after Account Opening Balance

        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if not text:
                    continue
                lines = [l.strip() for l in text.split("\n") if l.strip()]

                for ln in lines:
                    # Don't parse anything until we see Account Opening Balance
                    if not start_parsing:
                        if "ACCOUNT OPENING BALANCE" in ln.upper():
                            start_parsing = True
                        else:
                            continue   # skip all lines before opening balance

                    # Skip headers/separators
                    if re.match(r"^-{5,}", ln):
                        continue
                    if any(h in ln for h in ["Date", "Particulars", "Balance Amt", "Contra Id"]):
                        continue

                    # Handle Account Opening Balance
                    if "ACCOUNT OPENING BALANCE" in ln.upper():
                        amt_raw = ln.split(":")[-1].strip()
                        amt = parse_amount(amt_raw)
                        rows.append({
                            "Post Date": None,
                            "Tran": None,
                            "Ref Num": None,
                            "Particulars": "ACCOUNT OPENING BALANCE",
                            "Debit": None,
                            "Credit": amt,
                            "Balance": amt
                        })
                        continue

                    # Handle Brought Forward
                    if "BROUGHT FORWARD" in ln.upper():
                        parts_bf = ln.split()
                        amt_raw = parts_bf[-1]   # last token has CR/DR
                        amt = parse_amount(amt_raw)
                        rows.append({
                            "Post Date": None,
                            "Tran": None,
                            "Ref Num": None,
                            "Particulars": "BROUGHT FORWARD",
                            "Debit": None,
                            "Credit": None,
                            "Balance": amt
                        })
                        continue

                    # Transaction rows
                    parts = ln.split()
                    if len(parts) < 4:
                        continue

                    row = parse_transaction_line(parts)
                    rows.append(row)

        df = pd.DataFrame(rows)

        # Normalize string columns only
        str_cols = df.select_dtypes(include=["object"]).columns
        for c in str_cols:
            df[c] = df[c].astype(str).str.strip()
            df[c] = df[c].replace({"": None, "None": None})

        # Ensure numeric columns are float
        for col in ["Debit", "Credit", "Balance"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # --- Keywords ---
        keywords = []
        for d in df["Particulars"].fillna(""):
            for w in re.split(r"\W+", str(d)):
                if len(w) > 3:
                    keywords.append(w.upper())
        direction_counts = Counter(keywords)

        return df, direction_counts

    # === Streamlit UI ===
    def main():
        st.set_page_config(page_title="Indian Overseas Bank Statement Parser", page_icon="🏦", layout="wide")

        # Header
        st.title("🏦 Indian Overseas Bank Statement PDF Parser")
        st.write("Upload your Indian Overseas Bank PDF to extract metadata and transaction details.")

        # File uploader
        uploaded_file = st.file_uploader("📁 Upload your Indian Overseas Bank PDF", type=["pdf"])
        source = uploaded_file if uploaded_file else DEFAULT_FILE if os.path.exists(DEFAULT_FILE) else None

        if not source:
            st.error("❌ No file uploaded and default file not found.")
            st.stop()

        # Metadata
        metadata = extract_metadata_from_pdf(source)
        if metadata:
            with st.expander("📌 Extracted Metadata", expanded=True):
                st.dataframe(pd.DataFrame(metadata.items(), columns=["Field", "Value"]))

        # Transactions
        df, direction_counts = parse_iob_pdf(source)

        if df.empty:
            st.warning("⚠ No transactions found.")
        else:
            # Transaction stats
            total_txn = len(df)
            # count only real numeric debit/credit entries
            debit_txn = int(df["Debit"].notna().sum()) if "Debit" in df else 0
            credit_txn = int(df["Credit"].notna().sum()) if "Credit" in df else 0

            # also compute total amounts (optional, useful)
            total_debit_amount = float(df["Debit"].sum()) if "Debit" in df and not df["Debit"].dropna().empty else 0.0
            total_credit_amount = float(df["Credit"].sum()) if "Credit" in df and not df["Credit"].dropna().empty else 0.0
            total_balance = float(total_credit_amount - total_debit_amount)

            st.success(f"✅ Parsed {total_txn} transactions.")

            col1, col2, col3, col4, col5, col6 = st.columns([1,1,1,1.2,1.2,1.2])
            col1.metric("📊 Total Transactions", total_txn)
            col2.metric("⬇️ Debit Transactions", debit_txn)
            col3.metric("⬆️ Credit Transactions", credit_txn)
            col4.metric("⬇️ Total Debit ₹", f"{total_debit_amount:,.2f}")
            col5.metric("⬆️ Total Credit ₹", f"{total_credit_amount:,.2f}")
            col6.metric("💰 Balance ₹", f"{total_balance:,.2f}")

            # Show transactions
            st.subheader("🧾 Transactions")

            # Replace None/NaN with empty string for display
            display_df = df.fillna("")

            st.dataframe(display_df, use_container_width=True)


            # Frequent transaction keywords
            st.subheader("🔑 Frequent Transaction Keywords")

            direction_df = (
                pd.DataFrame(direction_counts.items(), columns=["Keyword", "Count"])
                .sort_values(by="Count", ascending=False)
            )
            direction_df = direction_df[direction_df["Count"] > 1]

            if not direction_df.empty:
                st.bar_chart(direction_df.set_index("Keyword"))
                with st.expander("📋 Detailed Keyword Counts"):
                    st.dataframe(direction_df, use_container_width=True)
            else:
                st.info("ℹ️ No frequent keywords found.")

            # Optional Download as Excel
            # output = BytesIO()
            # with pd.ExcelWriter(output, engine="openpyxl") as writer:
            #     df.to_excel(writer, index=False)
            # st.download_button("📥 Download as Excel", output.getvalue(), file_name="iob_bank_parsed.xlsx")

    main()


if __name__ == "__main__":
    run_pdf_parser_iob()
