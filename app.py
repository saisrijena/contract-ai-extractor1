import streamlit as st

st.title("AI Contract Extraction Tool")

st.write("Upload contract and extract land lease / throughput terms.")

uploaded_file = st.file_uploader("Upload Contract PDF", type=["pdf"])

if uploaded_file:
    st.success("File uploaded successfully!")
    st.write("Next step: PDF text extraction will be added.")
