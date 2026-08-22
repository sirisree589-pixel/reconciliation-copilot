import streamlit as st
import pandas as pd
from reconciler import reconcile, build_summary

st.set_page_config(page_title="Vendor Reconciliation Copilot", layout="wide")

st.title("📊 Vendor Reconciliation Copilot")
st.caption(
    "Upload a vendor statement of account and your internal ledger extract. "
    "The engine matches transactions by reference number, flags discrepancies, "
    "and computes a running reconciling balance."
)

with st.sidebar:
    st.header("1. Data source")
    use_sample = st.toggle("Use built-in sample data", value=True)

    vendor_file = None
    ledger_file = None
    if not use_sample:
        vendor_file = st.file_uploader("Vendor statement (CSV)", type="csv")
        ledger_file = st.file_uploader("Internal ledger (CSV)", type="csv")

    st.header("2. Summary style")
    use_llm = st.toggle("Use LLM for the natural-language summary", value=False)
    api_key = None
    if use_llm:
        api_key = st.text_input("Anthropic API key", type="password")
        st.caption("Key is only used for this session, never stored.")

if use_sample:
    vendor_df = pd.read_csv("sample_data/vendor_statement.csv")
    ledger_df = pd.read_csv("sample_data/internal_ledger.csv")
else:
    if not vendor_file or not ledger_file:
        st.info("Upload both files in the sidebar to run reconciliation, or toggle on sample data.")
        st.stop()
    vendor_df = pd.read_csv(vendor_file)
    ledger_df = pd.read_csv(ledger_file)

with st.expander("Preview raw input files"):
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Vendor statement")
        st.dataframe(vendor_df, use_container_width=True)
    with c2:
        st.subheader("Internal ledger")
        st.dataframe(ledger_df, use_container_width=True)

result = reconcile(vendor_df, ledger_df)

st.header("Reconciliation Overview")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Matched", len(result.matched))
m2.metric("Amount mismatches", len(result.amount_mismatches))
m3.metric("Vendor-only items", len(result.vendor_only))
m4.metric("Ledger-only items", len(result.ledger_only))

st.metric("Unexplained running balance (Vendor - Ledger)", f"{result.running_balance:,.2f}")

st.header("Plain-English Summary")
if use_llm and not api_key:
    st.warning("Enter an API key in the sidebar to use the LLM summary, showing template summary for now.")
    summary = build_summary(result, use_llm=False)
else:
    summary = build_summary(result, use_llm=use_llm, api_key=api_key)
st.write(summary)

st.header("Details")

tab1, tab2, tab3, tab4 = st.tabs([
    f"✅ Matched ({len(result.matched)})",
    f"⚠️ Mismatches ({len(result.amount_mismatches)})",
    f"📄 Vendor-only ({len(result.vendor_only)})",
    f"📒 Ledger-only ({len(result.ledger_only)})",
])

with tab1:
    st.dataframe(result.matched, use_container_width=True)
with tab2:
    st.dataframe(result.amount_mismatches, use_container_width=True)
    if len(result.amount_mismatches):
        st.caption("These references exist in both sources but the amounts don't agree - "
                   "likely a partial payment, a discount applied on one side only, or a data-entry error.")
with tab3:
    st.dataframe(result.vendor_only, use_container_width=True)
    if len(result.vendor_only):
        st.caption("These charges were billed by the vendor but haven't been recorded in our ledger yet.")
with tab4:
    st.dataframe(result.ledger_only, use_container_width=True)
    if len(result.ledger_only):
        st.caption("These are in our books but the vendor hasn't billed for them yet (e.g. accruals).")

st.divider()
st.caption(
    "Matching is done by exact reference-number join with a tolerance-based amount comparison "
    "(see reconciler.py). No LLM is involved in deciding what counts as a match - "
    "only in phrasing the optional natural-language summary above."
)
