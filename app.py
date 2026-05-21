import streamlit as st
import fitz
import pandas as pd
from io import BytesIO

st.title("AI Contract Extraction Tool")
st.write("Upload contract and prepare land lease / throughput commercial terms.")

uploaded_file = st.file_uploader("Upload Contract PDF", type=["pdf"])

def extract_pdf_text(file):
    doc = fitz.open(stream=file.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    return text

if uploaded_file:
    text = extract_pdf_text(uploaded_file)

    st.success("PDF Text Extracted Successfully!")

    st.subheader("Extracted Contract Text")
    st.text_area("Contract Content", text, height=300)

    st.subheader("Commercial Terms Table")

    df = pd.DataFrame({
        "Term Type": ["Land Lease"],
        "Start Date": [""],
        "End Date": [""],
        "Charge Type": [""],
        "Basis": [""],
        "Rate": [""],
        "Fixed Amount": [""],
        "Escalation": [""],
        "Remarks": [""]
    })

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
