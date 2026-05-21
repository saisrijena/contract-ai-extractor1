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

def clean_text(text):
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(\d+)\s*(st|nd|rd|th)", r"\1\2", text, flags=re.I)
    text = text.replace("AED 21,479, 280", "AED 21,479,280")
    return text

def extract_land_lease(text):
    rows = []

    pattern = r"(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4})\s+to\s+(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4})\s*=\s*AED\s*([\d,]+)"

    matches = re.findall(pattern, text, re.I)

    for start, end, amount in matches:
        rows.append({
            "Term Type": "Land Lease",
            "Start Date": start,
            "End Date": end,
            "Charge Type": "Fixed Revenue",
            "Basis": "Period-based",
            "Volume": "",
            "Rate": "",
            "Fixed Amount": "AED " + amount,
            "Escalation": "No",
            "Remarks": ""
        })

    if "2.5% escalation" in text:
        rows.append({
            "Term Type": "Land Lease",
            "Start Date": "25th October 2028",
            "End Date": "Ongoing",
            "Charge Type": "Escalation",
            "Basis": "Previous year revenue",
            "Volume": "",
            "Rate": "",
            "Fixed Amount": "",
            "Escalation": "2.5% year on year",
            "Remarks": "Escalation starts from 25th October 2028"
        })

    return rows

def extract_throughput(text):
    rows = []

    volume_pattern = r"(\d+)\s*Million\s+tons?\s+from\s+(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4})\s+to\s+(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4})"

    volume_matches = re.findall(volume_pattern, text, re.I)

    for volume, start, end in volume_matches:
        rows.append({
            "Term Type": "Throughput Volume",
            "Start Date": start,
            "End Date": end,
            "Charge Type": "Volume Commitment",
            "Basis": "Million Tons",
            "Volume": volume + " Million Tons",
            "Rate": "",
            "Fixed Amount": "",
            "Escalation": "",
            "Remarks": ""
        })

    rate_pattern = r"(Up to 15 Million tons|15 to 20 Million Tons|20 to 25 Million Tons)\s*[:=]\s*AED\s*([\d.]+)\s*per Ton"

    rate_matches = re.findall(rate_pattern, text, re.I)

    for slab, rate in rate_matches:
        rows.append({
            "Term Type": "Throughput Rate",
            "Start Date": "",
            "End Date": "",
            "Charge Type": "Product Handling Rate",
            "Basis": slab,
            "Volume": "",
            "Rate": "AED " + rate + " per Ton",
            "Fixed Amount": "",
            "Escalation": "2.5% year on year",
            "Remarks": ""
        })

    return rows

if uploaded_file:
    raw_text = extract_pdf_text(uploaded_file)
    text = clean_text(raw_text)

    st.success("PDF Text Extracted Successfully!")

    st.subheader("Extracted Contract Text")
    st.text_area("Contract Content", raw_text, height=300)

    rows = []
    rows.extend(extract_land_lease(text))
    rows.extend(extract_throughput(text))

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
