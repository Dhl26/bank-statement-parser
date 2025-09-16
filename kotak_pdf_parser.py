import streamlit as st
import pdfplumber
import pandas as pd
import re
import os
from io import BytesIO
from collections import Counter

def kotak_pdf_parser():
    DEFAULT_FILE = "kotak_stmt2.pdf"

    def extract_metadata_from_pdf(file):
        metadata = {}
        try:
            with pdfplumber.open(file) as pdf:
                lines = []
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        lines.extend(text.split("\n"))

            # Clean lines
            lines = [l.strip() for l in lines if l and l.strip()]

            metadata["Bank"] = "Kotak Mahindra Bank"

                        # --- Account Holder Name ---
            def _state_country_prefix(s: str) -> str:
                # Grab a leading token like "KARNATAKA,INDIA" (or "TAMIL NADU, INDIA", etc.)
                m = re.match(r'^\s*([A-Z][A-Z\s\-]+,?\s*INDIA)\b', s)
                return m.group(1).strip() if m else ""

            # --- Account Holder Name + Address ---
            holder_name = None
            addr_lines = []
            started = False
            address_mode = False

            for i, raw in enumerate(lines):
                line = raw.strip()
                if not line:
                    continue

                # Name can be on the same line as "Period :"
                if not started and not line.lower().startswith("kotak"):
                    holder_name = line.split("Period :", 1)[0].strip() if "Period :" in line else line
                    started = True
                    continue

                # Start capturing address after "Currency" (helps skip top-right block)
                if "Currency" in line and started:
                    address_mode = True
                    continue

                if not address_mode:
                    continue

                # If "Branch :" appears inline, keep only the left part and continue
                if "Branch :" in line:
                    left = line.split("Branch :", 1)[0].strip()
                    if left:
                        addr_lines.append(left)
                    continue

                # If "Nominee Registered" appears inline, keep only the left part and continue
                if "Nominee Registered" in line:
                    left = line.split("Nominee Registered", 1)[0].strip()
                    if left:
                        addr_lines.append(left)
                    continue

                # "Branch Address :" ends the holder address, but recover any state/country line that
                # got pushed to the next physical line by the two-column merge.
                if "Branch Address" in line:
                    before, _, after = line.partition("Branch Address")
                    if before.strip():
                        addr_lines.append(before.strip())

                    # peek NEXT line; if it starts with a state/country token, append just that token
                    if i + 1 < len(lines):
                        nxt = lines[i + 1].strip()
                        token = _state_country_prefix(nxt)
                        if token:
                            addr_lines.append(token)
                    break
                
                if "Bracnch Address" in line:
                    before, _, after = line.partition("Bracnch Address")
                    if before.strip():
                        addr_lines.append(before.strip())

                    # peek NEXT line; if it starts with a state/country token, append just that token
                    if i + 1 < len(lines):
                        nxt = lines[i + 1].strip()
                        token = _state_country_prefix(nxt)
                        if token:
                            addr_lines.append(token)
                    break

                # Normal address line
                addr_lines.append(line)

            metadata["Account Holder Name"] = holder_name or ""
            # Use newline join to keep lines distinct (you can switch to ", " if you prefer one line)
            metadata["Account Holder Address"] = "\n".join([l for l in addr_lines if l]).strip()


            # --- Right Side Details ---
            branch_addr_collect = False
            branch_addr_lines = []
            for i, line in enumerate(lines):
                clean_line = line.strip()

                if "Period" in clean_line:
                    metadata["Period"] = clean_line.split(":", 1)[-1].strip()
                if "Cust.Reln.No" in clean_line:
                    metadata["Cust.Reln.No"] = clean_line.split(":", 1)[-1].strip()
                if "Account No" in clean_line:
                    metadata["Account Number"] = clean_line.split(":", 1)[-1].strip()
                if "Currency" in clean_line:
                    metadata["Currency"] = clean_line.split(":", 1)[-1].strip()
                if "Branch :" in clean_line:
                    metadata["Branch"] = clean_line.split(":", 1)[-1].strip()
                if "Nominee Registered" in clean_line:
                    metadata["Nominee Registered"] = clean_line.split(":", 1)[-1].strip()

                # Collect multi-line branch address
                if "Branch Address" in clean_line or "Bracnch Address" in clean_line:
                    branch_addr_collect = True
                    branch_addr_lines.append(clean_line.split(":", 1)[-1].strip())
                    continue
                if branch_addr_collect:
                    if re.search(r"(Phone|MICR|IFSC|Email)", clean_line, re.I):
                        branch_addr_collect = False
                    else:
                        branch_addr_lines.append(clean_line)

                if "Branch Phone No." in clean_line:
                    metadata["Branch Phone"] = clean_line.split(":", 1)[-1].strip()
                if "MICR Code" in clean_line:
                    metadata["MICR Code"] = clean_line.split(":", 1)[-1].strip()
                if "IFSC Code" in clean_line:
                    metadata["IFSC Code"] = clean_line.split(":", 1)[-1].strip()

            metadata["Branch Address"] = " ".join(branch_addr_lines).strip()

        except Exception as e:
            print("Error extracting Kotak metadata:", e)

        return metadata



      # ------------------ Helpers ------------------ #
    def is_amount_token(tok: str) -> bool:
        """Return True if token is likely an amount (e.g. 3.00, 397.73, 0, 1,234.56, 45.00(Cr))."""
        if not isinstance(tok, str) or not tok.strip():
            return False
        s = tok.strip().replace(",", "")
        # remove Cr/Dr suffixes and parentheses for testing
        s = s.replace("(Cr)", "").replace("(Dr)", "").replace("Cr", "").replace("Dr", "")
        s = s.strip()
        # Must be numeric (with optional decimal), or a short integer (to exclude account numbers)
        if re.match(r"^-?\d+\.\d{1,2}$", s):  # decimal with 1-2 decimals
            return True
        if s.isdigit() and len(s) <= 6:  # small integers (0, 3, 1000) - account numbers are longer
            return True
        return False

    def parse_amount(val: str) -> float:
        """Safely parse withdrawal/deposit token to float; returns 0.0 on failure."""
        try:
            if not isinstance(val, str):
                val = str(val)
            s = val.replace(",", "").replace("(Cr)", "").replace("(Dr)", "").replace("Cr", "").replace("Dr", "").strip()
            if s == "" or s == "-" or s.upper() in ["NA", "N/A"]:
                return 0.0
            return float(s)
        except Exception:
            return 0.0

    def parse_balance(val: str) -> float:
        """Safely parse balance token to float; returns 0.0 on failure."""
        return parse_amount(val)


    # ------------------ Transaction Parser (fixed merging + narration) ------------------ #
    def parse_transactions(file):
        transactions = []
        keywords = []

        date_start_re = re.compile(r"^\d{2}-\d{2}-\d{4}\b")  # lines that start a transaction
        frag_month_year_re = re.compile(r"^\d{2}-\d{4}$")    # continuation like "06-2022"

        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                raw_lines = [l.strip() for l in text.split("\n") if l and l.strip()]

                # Merge broken lines: start buffers only when we see a date or "B/F"
                # Merge broken lines: handle cases like "to 30-" + "06-2022"
                merged_lines = []
                buffer = None
                raw_len = len(raw_lines)
                i = 0

                while i < raw_len:
                    ln = raw_lines[i].strip()

                    if date_start_re.match(ln) or ln.startswith("B/F"):
                        # push old buffer
                        if buffer:
                            merged_lines.append(buffer.strip())
                        buffer = ln
                        i += 1
                        continue

                    if buffer is None:
                        i += 1
                        continue

                    # CASE: line broken across rows like "to 30-" + "06-2022"
                    if buffer.endswith("-") and not date_start_re.match(ln):
                        buffer = buffer.rstrip("-") + ln   # join seamlessly
                        i += 1
                        continue

                    # otherwise treat as continuation
                    buffer += " " + ln
                    i += 1

                # push last
                if buffer:
                    merged_lines.append(buffer.strip())


                # Now parse merged lines
                for line in merged_lines:
                    # skip obvious non-transaction lines
                    if not line:
                        continue
                    if line.startswith("Statement Summary") or line.startswith("Date Narration") or line.startswith("Date "):
                        continue

                    parts = line.split()
                    if not parts:
                        continue

                    # Opening balance
                    if line.startswith("B/F"):
                        # Last token should be balance
                        bal_tok = parts[-1]
                        balance = parse_balance(bal_tok)
                        transactions.append({
                            "Date": "B/F",
                            "Narration": "Opening Balance",
                            "Chq/Ref No": "",
                            "Withdrawal (Dr)": 0.0,
                            "Deposit (Cr)": 0.0,
                            "Balance": balance
                        })
                        continue

                    # If first token is not a date, skip (safety)
                    if not date_start_re.match(parts[0]):
                        continue

                    # Collect numeric token indices (amount-like) — careful to avoid account numbers
                    num_indices = [i for i, t in enumerate(parts) if is_amount_token(t)]
                    if not num_indices:
                        # nothing recognizable as amounts -> skip
                        continue

                    # The last numeric-like token is balance
                    balance_idx = num_indices[-1]
                    balance = parse_balance(parts[balance_idx])

                    # deposit is the numeric token just before balance (if present)
                    deposit = parse_amount(parts[num_indices[-2]]) if len(num_indices) >= 2 else 0.0
                    # withdrawal is the numeric token before deposit (if present)
                    withdrawal = parse_amount(parts[num_indices[-3]]) if len(num_indices) >= 3 else 0.0

                    # narration ends before the earliest amount used for withdrawal (if present),
                    # else before deposit or balance accordingly
                    if len(num_indices) >= 3:
                        narration_end = num_indices[-3]
                    elif len(num_indices) == 2:
                        narration_end = num_indices[-2]
                    else:
                        narration_end = num_indices[-1]

                    # narration is everything between date token (index 0) and narration_end
                    narration_tokens = parts[1:narration_end]
                    narration = " ".join(narration_tokens).strip()

                    # fix awkward trailing hyphens in narration (e.g. "to 30-")
                    narration = re.sub(r"\s+-\s*$", "-", narration)               # remove trailing space-dash
                    narration = re.sub(r"-\s+(\d{2}-\d{4})", r"-\1", narration)    # ensure "30- 06-2022" -> "30-06-2022"

                    # collect keywords for frequency
                    for w in re.split(r"\W+", narration):
                        if len(w) > 3:
                            keywords.append(w.upper())

                    transactions.append({
                        "Date": parts[0],
                        "Narration": narration,
                        "Chq/Ref No": "",
                        "Withdrawal (Dr)": withdrawal,
                        "Deposit (Cr)": deposit,
                        "Balance": balance
                    })

        df = pd.DataFrame(transactions)
        return df, Counter(keywords)


    # ------------------ Streamlit UI ------------------ #
    def main():
        st.set_page_config(page_title="Kotak Bank Statement Parser", page_icon="🏦", layout="wide")

        st.title("🏦 Kotak Bank Statement PDF Parser")
        st.write("Upload your Kotak Bank PDF to extract metadata and transaction details.")

        uploaded_file = st.file_uploader("📁 Upload Kotak Bank PDF", type=["pdf"])
        source = uploaded_file if uploaded_file else DEFAULT_FILE if os.path.exists(DEFAULT_FILE) else None

        if not source:
            st.error("❌ No file uploaded and default file not found.")
            st.stop()

        st.success("✅ Using uploaded file." if uploaded_file else "📄 Using default test file.")

        metadata = extract_metadata_from_pdf(source)
        if metadata:
            with st.expander("📌 Extracted Metadata", expanded=True):
                st.dataframe(pd.DataFrame(metadata.items(), columns=["Field", "Value"]).fillna(""))

        df, direction_counts = parse_transactions(source)

        if df.empty:
            st.warning("⚠ No transactions found.")
            return

        # Ensure numeric columns
        for col in ["Withdrawal (Dr)", "Deposit (Cr)", "Balance"]:
            if col in df:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

        total_txn = len(df)
        debit_txn = int((df["Withdrawal (Dr)"] > 0).sum()) if "Withdrawal (Dr)" in df else 0
        credit_txn = int((df["Deposit (Cr)"] > 0).sum()) if "Deposit (Cr)" in df else 0
        total_debit_amount = float(df["Withdrawal (Dr)"].sum()) if "Withdrawal (Dr)" in df else 0.0
        total_credit_amount = float(df["Deposit (Cr)"].sum()) if "Deposit (Cr)" in df else 0.0
        closing_balance = float(df["Balance"].iloc[-1]) if "Balance" in df and not df["Balance"].empty else 0.0

        st.success(f"✅ Parsed {total_txn} transactions.")

        cols = st.columns([1, 1, 1, 1.2, 1.2, 1.2])
        cols[0].metric("📊 Total Transactions", total_txn)
        cols[1].metric("⬇️ Debit Transactions", debit_txn)
        cols[2].metric("⬆️ Credit Transactions", credit_txn)
        cols[3].metric("⬇️ Total Debit ₹", f"{total_debit_amount:,.2f}")
        cols[4].metric("⬆️ Total Credit ₹", f"{total_credit_amount:,.2f}")
        cols[5].metric("🏦 Closing Balance ₹", f"{closing_balance:,.2f}")

        # Replace None/NaN with empty string for display
        display_df = df.fillna("").copy()

        st.subheader("🧾 Transactions")
        st.dataframe(display_df, use_container_width=True)

        # Frequent transaction keywords
        st.subheader("🔑 Frequent Transaction Keywords")
        direction_df = pd.DataFrame(direction_counts.items(), columns=["Keyword", "Count"]).sort_values(by="Count", ascending=False)
        direction_df = direction_df[direction_df["Count"] > 1]
        if not direction_df.empty:
            st.bar_chart(direction_df.set_index("Keyword"))
            with st.expander("📋 Detailed Keyword Counts"):
                st.dataframe(direction_df, use_container_width=True)
        else:
            st.info("ℹ️ No frequent keywords found.")

        # Excel download
        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False)
        st.download_button("📥 Download as Excel", output.getvalue(), file_name="kotak_bank_parsed.xlsx")

    main()


if __name__ == "__main__":
    kotak_pdf_parser()