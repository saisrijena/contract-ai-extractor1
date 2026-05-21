import streamlit as st
import fitz

st.title("AI Contract Extraction Tool")

st.write("Upload contract and extract land lease / throughput terms.")

uploaded_file = st.file_uploader(
    "Upload Contract PDF",
    type=["pdf"]
)

def extract_pdf_text(file):

    doc = fitz.open(
        stream=file.read(),
        filetype="pdf"
    )

    text = ""

    for page in doc:
        text += page.get_text()

    return text

if uploaded_file:

    text = extract_pdf_text(uploaded_file)

    st.success("PDF Text Extracted Successfully!")

    st.subheader("Extracted Contract Text")

    st.text_area(
        "Contract Content",
        text,
        height=500
    )
