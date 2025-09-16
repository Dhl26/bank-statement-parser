import streamlit as st
import pdfplumber
import pandas as pd
import re
import os
from io import BytesIO
from collections import Counter

def run_pdf_parser():
    # === CONFIG ===
    DEFAULT_FILE = "Statement (2).pdf"

    # === Extract Metadata ===
    def extract_metadata_from_pdf(file):
        metadata = {}
        lines = []

        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    lines = text.split('\n')
                    for line in lines:
                        line = line.strip()
                        if re.match(r"^\d{2}/\d{2}/\d{2}\s+\d{2}/\d{2}/\d{2}", line):
                            break
                        lines.append(line)
                    break  # only the first page has metadata

        full_text = "\n".join(lines)

        metadata["Bank"] = "CENTRAL BANK OF INDIA"
        metadata["Branch"] = next((l for l in lines if "ROAD" in l and "EXTN" in l), "") or ""

        metadata["Branch Email"] = re.search(r"Branch E-mail\s*:\s*(\S+)", full_text)
        metadata["Branch Email"] = metadata["Branch Email"].group(1) if metadata["Branch Email"] else ""

        metadata["Branch Code"] = re.search(r"Branch Code\s*:\s*(\d+)", full_text)
        metadata["Branch Code"] = metadata["Branch Code"].group(1) if metadata["Branch Code"] else ""

        metadata["Account Number"] = re.search(r"Account No.\s*:\s*(\d+)", full_text)
        metadata["Account Number"] = metadata["Account Number"].group(1) if metadata["Account Number"] else ""

        metadata["Currency"] = re.search(r"Currency\s*:\s*(\w+)", full_text)
        metadata["Currency"] = metadata["Currency"].group(1) if metadata["Currency"] else ""

        metadata["Product"] = re.search(r"Product\s*:\s*(.*)", full_text)
        metadata["Product"] = metadata["Product"].group(1).strip() if metadata["Product"] else ""

        metadata["Nomination"] = re.search(r"Nomination\s*:\s*(\w+)", full_text)
        metadata["Nomination"] = metadata["Nomination"].group(1) if metadata["Nomination"] else ""

        metadata["Statement Date"] = re.search(r"Date\s*:\s*(\d{2}/\d{2}/\d{4})", full_text)
        metadata["Statement Date"] = metadata["Statement Date"].group(1) if metadata["Statement Date"] else ""

        metadata["Statement Time"] = re.search(r"Time\s*:\s*(\d{2}:\d{2}:\d{2})", full_text)
        metadata["Statement Time"] = metadata["Statement Time"].group(1) if metadata["Statement Time"] else ""

        metadata["Email"] = re.search(r"E-mail\s*:\s*(\S+)", full_text)
        metadata["Email"] = metadata["Email"].group(1) if metadata["Email"] else ""

        match = re.search(r"Statement From\s+(\d{2}/\d{2}/\d{4})\s+to\s+(\d{2}/\d{2}/\d{4})", full_text)
        metadata["Statement Period"] = f"{match.group(1)} to {match.group(2)}" if match else ""

        metadata["Customer Name"] = next(
            (l for l in lines if l.isupper() and ":" not in l and "CENTRAL BANK" not in l), ""
        ) or ""

        address_lines = []
        for line in lines:
            if "Account No." in line:
                break
            if any(char.isdigit() for char in line) or "ROAD" in line or "BANGALORE" in line:
                address_lines.append(line)
        metadata["Address"] = ", ".join(address_lines) if address_lines else ""

        # Ensure no None values
        for k, v in metadata.items():
            if v is None:
                metadata[k] = ""

        return metadata

    # === Helper ===
    def parse_amount(value):
        if not value or value == '-':
            return 0.00
        return float(value.replace(',', ''))

    def parse_balance(value):
        if not value:
            return 0.00
        value = value.replace(',', '')
        return float(value.replace("Cr", "").replace("Dr", "").strip())

    # === Parser ===
    def parse_central_bank_pdf(file):
        transactions = []
        opening_balance = None
        last_txn = None
        last_balance = None
        all_keys = []

        txn_pattern = re.compile(
            r"^(\d{2}/\d{2}/\d{2})\s+(\d{2}/\d{2}/\d{2})\s+(.*?)\s+\.\s+(.*?)\s+([\d,]+\.\d{2}|-)\s+([\d,]+\.\d{2}Cr)$"
        )

        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                lines = page.extract_text().split('\n')

                for line in lines:
                    line = line.strip()

                    if "BROUGHT FORWARD" in line.upper() and opening_balance is None:
                        match = re.search(r"([\d,]+\.\d{2})\s*(Cr|Dr)", line, re.IGNORECASE)
                        if match:
                            amount = match.group(1)
                            crdr = match.group(2)
                            opening_balance = parse_balance(f"{amount}{crdr}")

                    txn_match = txn_pattern.match(line)
                    if txn_match:
                        val_date, post_date = txn_match.group(1), txn_match.group(2)
                        description, chq_no = txn_match.group(3).strip(), txn_match.group(4).strip()
                        amount = parse_amount(txn_match.group(5))
                        balance = parse_balance(txn_match.group(6))

                        short_key_match = re.match(r'^([A-Z.\s]+)', description)
                        short_key = short_key_match.group(1).strip().upper() if short_key_match else ""
                        all_keys.append(short_key)

                        credit = debit = ""
                        if last_balance is not None:
                            if balance > last_balance:
                                credit = f"{amount:.2f}"
                            elif balance < last_balance:
                                debit = f"{amount:.2f}"
                        last_balance = balance

                        last_txn = {
                            "Value Date": val_date or "",
                            "Post Date": post_date or "",
                            "Details": description or "",
                            "Chq.No.": "" if chq_no == '-' else chq_no or "",
                            "Debit": debit or "",
                            "Credit": credit or "",
                            "Balance": f"{balance:.2f}" if balance is not None else "",
                            "More Info": ""
                        }
                        transactions.append(last_txn)

                    elif line.startswith(". .") and last_txn:
                        extra = line.replace(". .", "").strip().strip('.')
                        last_txn["More Info"] += " " + extra

        df = pd.DataFrame(transactions)

        # Replace None/NaN with empty string for display
        df = df.fillna("")
        direction_counts = Counter(all_keys)

        return df, Counter(all_keys), opening_balance, direction_counts

    # === Streamlit UI ===
    def main():
        st.set_page_config(page_title="CBI Bank Statement Parser", page_icon="🏦", layout="wide")

        # Header
        st.title("🏦 CBI Bank Statement PDF Parser")
        st.write("Upload your CBI Bank PDF to extract metadata and transaction details.")

        # File uploader
        uploaded_file = st.file_uploader("📁 Upload your CBI Bank PDF", type=["pdf"])
        source = uploaded_file if uploaded_file else DEFAULT_FILE if os.path.exists(DEFAULT_FILE) else None

        if not source:
            st.error("❌ No file uploaded and default file not found.")
            st.stop()

        # Metadata
        metadata = extract_metadata_from_pdf(source)
        if metadata:
            with st.expander("📌 Extracted Metadata", expanded=True):
                st.dataframe(pd.DataFrame(metadata.items(), columns=["Field", "Value"]))

        # ✅ Unpack all 4 values properly
        df, all_keys_count, opening_balance, direction_counts = parse_central_bank_pdf(source)

        if df.empty:
            st.warning("⚠ No transactions found.")
        else:
            # Transaction stats
            # Convert Debit & Credit safely
            df["Debit"] = pd.to_numeric(df["Debit"], errors="coerce").fillna(0.0)
            df["Credit"] = pd.to_numeric(df["Credit"], errors="coerce").fillna(0.0)

            # Transaction stats
            total_txn = len(df)
            debit_txn = (df["Debit"] > 0).sum()
            credit_txn = (df["Credit"] > 0).sum()

            total_debit_amount = df["Debit"].sum()
            total_credit_amount = df["Credit"].sum()
            total_balance = total_credit_amount - total_debit_amount

            st.success(f"✅ Parsed {total_txn} transactions.")

            col1, col2, col3, col4, col5, col6 = st.columns([1,1,1,1.2,1.2,1.2])
            col1.metric("📊 Total Transactions", total_txn)
            col2.metric("⬇️ Debit Transactions", debit_txn)
            col3.metric("⬆️ Credit Transactions", credit_txn)
            col4.metric("⬇️ Total Debit ₹", f"{total_debit_amount:,.2f}")
            col5.metric("⬆️ Total Credit ₹", f"{total_credit_amount:,.2f}")
            col6.metric("💰 Balance ₹", f"{total_balance:,.2f}")

            # Opening balance info if available
            if opening_balance is not None:
                st.info(f"📌 Opening Balance: ₹ {opening_balance:,.2f}")

            # Show transactions
            st.subheader("🧾 Transactions")
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

    main()
    
if __name__ == "__main__":
    run_pdf_parser()
