import streamlit as st
from sbi_pdf_parser import run_pdf_parser_sbi
from pdf_parser import run_pdf_parser
from kotak_pdf_parser import kotak_pdf_parser

# === FIRST: set page config ===
st.set_page_config(page_title="Bank Statement Toolkit", layout="wide")

# === PASSWORD PROTECTION ===
def authenticate():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        st.title("🔒 Secure Access")
        password = st.text_input("Enter password to access the app:", type="password")

        if password == "1234":  # 🔐 Replace with your actual password
            st.session_state.authenticated = True
            st.success("🔓 Access granted!")
        elif password:
            st.error("❌ Incorrect password. Please try again.")

    return st.session_state.authenticated


if authenticate():
    st.sidebar.title("🔍 Select Bank")

    mode = st.sidebar.selectbox(
        "Choose a Bank:",
        ["Kotak Bank Statement", "SBI Bank Statement", "CBI Bank Statement"]
    )

    if mode == "SBI Bank Statement":
        run_pdf_parser_sbi()
    elif mode == "CBI Bank Statement":
        run_pdf_parser()
    elif mode == "Kotak Bank Statement":
        kotak_pdf_parser()
