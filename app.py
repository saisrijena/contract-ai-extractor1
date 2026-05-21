import streamlit as st
import fitz
import pandas as pd
import re
from io import BytesIO

st.title("AI Contract Extraction Tool")

uploaded_file = st.file_uploader("Upload Contract PDF", type=["pdf"])

def extract_pdf_text(file):
    doc = fitz.open(stream=file.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    return text

def find_value(pattern, text):
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else ""

if uploaded_file:
    text = extract_pdf_text(uploaded_file)

    st.success("PDF Text Extracted Successfully!")

    st.subheader("Extracted Contract Text")
    st.text_area("Contract Content", text, height=300)

    effective_date = find_value(r"Effective Date[:\s]*([\w\s\d]+)", text)
    contract_term = find_value(r"Contract Term[:\s]*([\w\s\d]+)", text)
    total_area = find_value(r"Total Area[:\s]*([\d,]+\s*Sq\.?\s*m)", text)
    escalation = find_value(r"(\d+\.?\d*%\s*escalation)", text)

    amounts = re.findall(r"AED\s?[\d,]+", text, re.IGNORECASE)

    rows = []

    for amount in amounts:
        rows.append({
            "Term Type": "Land Lease",
            "Start Date": effective_date,
            "End Date": "",
            "Charge Type": "Fixed Revenue",
            "Basis": "Period-based",
            "Rate": "",
            "Fixed Amount": amount,
            "Escalation": escalation,
            "Remarks": f"Contract Term: {contract_term}, Area: {total_area}"
        })

    if not rows:
        rows.append({
            "Term Type": "Land Lease",
            "Start Date": effective_date,
            "End Date": "",
            "Charge Type": "",
            "Basis": "",
            "Rate": "",
            "Fixed Amount": "",
            "Escalation": escalation,
            "Remarks": f"Contract Term: {contract_term}, Area: {total_area}"
        })

    df = pd.DataFrame(rows)

    st.subheader("Commercial Terms Table")
    edited_df = st.data_editor(df, num_rows="dynamic")

    output = BytesIO()
    edited_df.to_excel(output, index=False)
    output.seek(0)

    st.download_button(
        "Download Excel",
        data=output,
        file_name="contract_terms.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
