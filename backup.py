import streamlit as st
import pandas as pd
import os
import plotly.express as px
from datetime import datetime

def run_excel_parser:
    # === CONFIG ===
    DEFAULT_FILE = "9921201000295_2020-till.xlsx"

    # Step 1: Remove empty rows and columns (None / NaN)
    def clean_dataframe(df):
        df = df.dropna(how='all', axis=0)  # Remove completely empty rows
        df = df.dropna(how='all', axis=1)  # Remove completely empty columns
        return df

    # Step 2: Detect the header row dynamically
    def find_header_row(df):
        keywords = ['date', 'description', 'credit', 'debit', 'amount', 'balance']
        for i, row in df.iterrows():
            values = [str(cell).lower() for cell in row if pd.notnull(cell)]
            if any(any(keyword in val for keyword in keywords) for val in values):
                return i
        return None

    # Step 3: Extract metadata above the header row
    def extract_raw_metadata(df, header_row):
        return df.iloc[:header_row].reset_index(drop=True) if header_row else pd.DataFrame()

    # Step 4: Process uploaded or default file
    def process_file(source):
        raw_df = pd.read_excel(source, header=None)
        header_row = find_header_row(raw_df)
        metadata_df = extract_raw_metadata(raw_df, header_row)

        # Load structured data using detected header row
        if header_row is not None:
            data_df = pd.read_excel(source, header=header_row)
        else:
            data_df = raw_df  # fallback
        return metadata_df, data_df

    # Step 5: Try parsing date/time columns into a uniform format
    def normalize_datetime_columns(df):
        for col in df.columns:
            try:
                df[col] = pd.to_datetime(df[col])
            except (ValueError, TypeError):
                pass
        return df

    # === MAIN APP ===
    def main():
        st.set_page_config(page_title="Bank Statement Structurer", layout="wide")
        st.title("📄 Bank Statement Structurer")

        uploaded_file = st.file_uploader("📁 Upload a heterogeneous Excel bank statement", type=["xlsx", "xls"])

        # Use uploaded or default file
        if uploaded_file is not None:
            source = uploaded_file
            st.success("✅ Using uploaded file.")
        elif os.path.exists(DEFAULT_FILE):
            source = DEFAULT_FILE
            st.warning("⚠ No file uploaded. Using default test file.")
        else:
            st.error("❌ No file uploaded and default file not found.")
            return

        metadata_df, transaction_df = process_file(source)

        transaction_df = clean_dataframe(transaction_df)
        metadata_df = clean_dataframe(metadata_df)
        transaction_df = normalize_datetime_columns(transaction_df)

        # Display Metadata
        if not metadata_df.empty:
            st.subheader("📌 Metadata Rows (Before Transaction Table Starts)")
            st.dataframe(metadata_df, use_container_width=True)

        st.subheader("📊 Structured Transactions")
        st.dataframe(transaction_df, use_container_width=True)

        # Grouping section
        st.subheader("🔍 Analyze and Group Transactions")

        if not transaction_df.empty:
            group_by_column = st.selectbox("Select a column to group by", transaction_df.columns)

            if pd.api.types.is_datetime64_any_dtype(transaction_df[group_by_column]):
                # Add options to group by Date, Month, Year, etc.
                date_option = st.selectbox("Group datetime by", ["Full Timestamp", "Date", "Month", "Year"])
                if date_option == "Date":
                    transaction_df[group_by_column] = transaction_df[group_by_column].dt.date
                elif date_option == "Month":
                    transaction_df[group_by_column] = transaction_df[group_by_column].dt.to_period("M").astype(str)
                elif date_option == "Year":
                    transaction_df[group_by_column] = transaction_df[group_by_column].dt.year
                # "Full Timestamp" does nothing, keeps as-is

            grouped = transaction_df.groupby(group_by_column).size().reset_index(name="Count")

            st.subheader("📌 Grouped Summary")
            st.dataframe(grouped, use_container_width=True)

            # Visualization
            st.subheader("📈 Visualize Grouping")
            fig = px.bar(grouped, x=group_by_column, y="Count", title=f"Count by {group_by_column}")
            st.plotly_chart(fig, use_container_width=True)

