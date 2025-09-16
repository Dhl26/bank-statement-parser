import streamlit as st
import pdfplumber
import pandas as pd
import re
import os
from io import BytesIO
from collections import Counter

def run_pdf_parser_sbi():
    # === CONFIG ===
    DEFAULT_FILE = "Statement1.pdf"

    # === Extract Metadata (SBI Format) ===
    def extract_metadata_from_pdf(file):
        metadata = {}
        lines = []

        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    lines = text.split("\n")
                    break  # only first page needed

        full_text = "\n".join(lines)
        metadata["Bank"] = "STATE BANK OF INDIA"

        try:
            idx = lines.index("STATEMENT OF ACCOUNT")

            # Account holder name
            metadata["Account Holder Name"] = lines[idx + 3].strip()

            # Address block
            addr_lines = []
            stop_words = ["BRANCH CODE", "CIF", "ACCOUNT NO", "IFSC", "DATE OF STATEMENT",
                        "TIME OF STATEMENT", "MICR CODE", "BALANCE", "STATEMENT FROM"]

            for i in range(idx + 5, len(lines)):
                text = lines[i].strip()

                # If line contains unwanted inline fields, cut them out
                if "BRANCH EMAIL" in text.upper():
                    text = text[:text.upper().find("BRANCH EMAIL")].strip()
                if "BRANCH PHONE" in text.upper():
                    text = text[:text.upper().find("BRANCH PHONE")].strip()

                # Stop collecting if we hit a real metadata keyword line
                if any(text.upper().startswith(word) for word in stop_words):
                    break

                if text:  # avoid blanks
                    addr_lines.append(text)

            metadata["Account Holder Address"] = " ".join(addr_lines).strip()

        except ValueError:
            metadata["Account Holder Name"] = ""
            metadata["Account Holder Address"] = ""

        # --- Branch & Address ---
        branch_name = ""
        branch_address = ""
        for i, line in enumerate(lines):
            if "STATE BANK OF INDIA" in line.upper():
                if i + 1 < len(lines):
                    branch_name = lines[i + 1].strip()
                if i + 2 < len(lines) and not lines[i + 2].startswith("Branch Code"):
                    branch_address = lines[i + 2].strip()
                break
        metadata["Branch"] = branch_name
        metadata["Branch Address"] = branch_address

        # --- Regex fields ---
        metadata["Branch Code"] = re.search(r"Branch Code\s*:\s*(\d+)", full_text)
        metadata["Branch Code"] = metadata["Branch Code"].group(1) if metadata["Branch Code"] else ""

        metadata["Branch Email"] = re.search(r"Branch Email\s*:\s*([\w\.-]+@[\w\.-]+)", full_text)
        metadata["Branch Email"] = metadata["Branch Email"].group(1) if metadata["Branch Email"] else ""

        metadata["Branch Phone"] = re.search(r"Branch Phone\s*:\s*(\d+)", full_text)
        metadata["Branch Phone"] = metadata["Branch Phone"].group(1) if metadata["Branch Phone"] else ""

        metadata["CIF"] = re.search(r"CIF\s*No\s*:\s*(\d+)", full_text)
        metadata["CIF"] = metadata["CIF"].group(1) if metadata["CIF"] else ""

        metadata["Account Number"] = re.search(r"Account\s*No\s*:\s*(\d+)", full_text)
        metadata["Account Number"] = metadata["Account Number"].group(1) if metadata["Account Number"] else ""

        metadata["Product"] = re.search(r"Product\s*:\s*(.*)", full_text)
        metadata["Product"] = metadata["Product"].group(1).strip() if metadata["Product"] else ""

        metadata["IFSC"] = re.search(r"IFSC\s*Code\s*:\s*([A-Z0-9]+)", full_text)
        metadata["IFSC"] = metadata["IFSC"].group(1) if metadata["IFSC"] else ""

        metadata["MICR"] = re.search(r"MICR\s*Code\s*:\s*(\d+)", full_text)
        metadata["MICR"] = metadata["MICR"].group(1) if metadata["MICR"] else ""

        metadata["Currency"] = re.search(r"Currency\s*:\s*([A-Z]+)", full_text)
        metadata["Currency"] = metadata["Currency"].group(1) if metadata["Currency"] else ""

        metadata["Account Status"] = re.search(r"Account\s*Status\s*:\s*(\w+)", full_text)
        metadata["Account Status"] = metadata["Account Status"].group(1) if metadata["Account Status"] else ""

        metadata["Nominee"] = re.search(r"Nominee\s*Name\s*:\s*(.*)", full_text)
        metadata["Nominee"] = metadata["Nominee"].group(1).strip() if metadata["Nominee"] else ""

        metadata["CKYC"] = re.search(r"CKYC\s*No\s*:\s*(.*)", full_text)
        metadata["CKYC"] = metadata["CKYC"].group(1).strip() if metadata["CKYC"] else ""

        metadata["Email"] = re.search(r"Email\s*:\s*(.*)", full_text)
        metadata["Email"] = metadata["Email"].group(1).strip() if metadata["Email"] else ""

        metadata["Statement Period"] = re.search(
            r"Statement\s*From\s*:\s*(\d{2}-\d{2}-\d{4})\s*To\s*(\d{2}-\d{2}-\d{4})", full_text
        )
        metadata["Statement Period"] = (
            f"{metadata['Statement Period'].group(1)} to {metadata['Statement Period'].group(2)}"
            if metadata["Statement Period"]
            else ""
        )

        return metadata

    def parse_amount(value):
        """
        Robust amount parser:
        - returns None for empty / '-' / missing values
        - strips CR/DR, commas, parentheses and other non-numeric chars
        - returns float or None
        """
        if value is None:
            return None
        s = str(value).strip()
        if s == "" or s == "-" or s.upper() in ["NA", "N/A", "—", "–"]:
            return None

        # Remove CR/DR markers and convert parentheses to negative sign if present
        s_up = s.upper()
        s_up = s_up.replace("CR", "").replace("DR", "")
        # Convert (1,000) => -1000
        if "(" in s_up and ")" in s_up:
            s_up = s_up.replace("(", "-").replace(")", "")

        # Remove anything that's not digit, dot or minus
        s_clean = re.sub(r"[^\d\.-]", "", s_up)

        if s_clean == "" or s_clean == "-" or s_clean == ".": 
            return None

        try:
            return float(s_clean)
        except Exception:
            return None

    # === Transaction Parser ===
    def parse_sbi_pdf(file_path, debug: bool = False):
        rows = []

        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                table = page.extract_table()
                if not table:
                    continue

                for row in table:
                    if not row or all(cell is None for cell in row):
                        continue

                    # Detect and skip headers on every page
                    if any("Post Date" in str(cell) for cell in row) or \
                       any("Debit" in str(cell) for cell in row) or \
                       any("Credit" in str(cell) for cell in row):
                        continue

                    # unpack with safe defaults (7 columns expected)
                    post_date, value_date, description, cheque, debit, credit, balance = (row + [None]*7)[:7]

                    # Handle BROUGHT FORWARD
                    if description and "BROUGHT FORWARD" in str(description).upper():
                        rows.append({
                            "Post Date": None,
                            "Value Date": None,
                            "Description": "BROUGHT FORWARD",
                            "Cheque No/Reference": None,
                            "Debit": None,
                            "Credit": None,
                            "Balance": parse_amount(balance)
                        })
                        continue

                    rows.append({
                        "Post Date": post_date,
                        "Value Date": value_date,
                        "Description": description,
                        "Cheque No/Reference": cheque,
                        "Debit": parse_amount(debit),
                        "Credit": parse_amount(credit),
                        "Balance": parse_amount(balance)
                    })

        df = pd.DataFrame(rows)

        # Normalize strings: strip whitespace from string columns and replace empty strings with NaN
        str_cols = df.select_dtypes(include=["object"]).columns.tolist()
        for c in str_cols:
            df[c] = df[c].astype(object).where(df[c].notna(), None)  # keep None
            df[c] = df[c].apply(lambda x: x.strip() if isinstance(x, str) else x)
        # Replace empty strings with pd.NA so dropna will work
        df = df.replace(r'^\s*$', pd.NA, regex=True)

        # Ensure numeric columns are numeric (coerce invalid -> NaN)
        if "Debit" in df:
            df["Debit"] = pd.to_numeric(df["Debit"], errors="coerce")
        if "Credit" in df:
            df["Credit"] = pd.to_numeric(df["Credit"], errors="coerce")
        if "Balance" in df:
            df["Balance"] = pd.to_numeric(df["Balance"], errors="coerce")

        # 🧹 Remove rows where all important fields are empty/NaN
        df = df.dropna(how="all", subset=["Post Date", "Value Date", "Description", "Cheque No/Reference", "Debit", "Credit", "Balance"])

        # Optional: reset index
        df = df.reset_index(drop=True)

        # Build keyword frequency (after dropping empty rows)
        keywords = []
        for d in df["Description"].fillna(""):
            for w in re.split(r"\W+", str(d)):
                if len(w) > 3:
                    keywords.append(w.upper())
        direction_counts = Counter(keywords)

        return df, direction_counts

    # === Streamlit UI ===
    def main():
        st.set_page_config(page_title="SBI Bank Statement Parser", page_icon="🏦", layout="wide")

        # Header
        st.title("🏦 SBI Bank Statement PDF Parser")
        st.write("Upload your SBI Bank PDF to extract metadata and transaction details.")

        # File uploader
        uploaded_file = st.file_uploader("📁 Upload your SBI Bank PDF", type=["pdf"])
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
        df, direction_counts = parse_sbi_pdf(source)

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
            # st.download_button("📥 Download as Excel", output.getvalue(), file_name="sbi_bank_parsed.xlsx")

    main()


if __name__ == "__main__":
    run_pdf_parser_sbi()
