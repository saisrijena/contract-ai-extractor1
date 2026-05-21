import streamlit as st
import fitz
import pandas as pd
import re
from io import BytesIO
from datetime import datetime

st.set_page_config(page_title="AI Contract Revenue Projection Tool", layout="wide")
st.title("AI Contract Extraction & Revenue Projection Tool")

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
    text = re.sub(r"(\d+)\s*(st|nd|rd|th)", r"\1", text, flags=re.I)
    text = text.replace("Oct ", "October ")
    text = text.replace("Sept ", "September ")
    text = text.replace("Sep ", "September ")
    text = re.sub(r"(\d),\s+(\d)", r"\1,\2", text)
    return text

def parse_date(date_text):
    date_text = str(date_text).strip()
    date_text = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_text, flags=re.I)
    date_text = date_text.replace("Oct", "October")
    date_text = date_text.replace("Sept", "September")
    date_text = date_text.replace("Sep", "September")
    date_text = re.sub(r"\s+", " ", date_text)

    formats = ["%d %B %Y", "%d %b %Y"]
    for fmt in formats:
        try:
            return datetime.strptime(date_text, fmt)
        except:
            pass
    return None

def clean_amount(amount):
    return float(str(amount).replace(",", "").replace(" ", ""))

def get_overlap_days(start1, end1, start2, end2):
    latest_start = max(start1, start2)
    earliest_end = min(end1, end2)
    days = (earliest_end - latest_start).days + 1
    return max(0, days)

def quarter_ranges(start_year, end_year):
    quarters = []
    for y in range(start_year, end_year + 1):
        quarters += [
            (f"Q1 {y}", datetime(y, 1, 1), datetime(y, 3, 31)),
            (f"Q2 {y}", datetime(y, 4, 1), datetime(y, 6, 30)),
            (f"Q3 {y}", datetime(y, 7, 1), datetime(y, 9, 30)),
            (f"Q4 {y}", datetime(y, 10, 1), datetime(y, 12, 31)),
        ]
    return quarters

def extract_effective_date(text):
    pattern = r"Effective Date[:\s]*([0-9]{1,2}\s+\w+\s+[0-9]{4})"
    match = re.search(pattern, text, re.I)
    return parse_date(match.group(1)) if match else None

def extract_area(text):
    pattern = r"Total Area[:\s]*([\d,]+)\s*Sq"
    match = re.search(pattern, text, re.I)
    return clean_amount(match.group(1)) if match else None

def extract_escalation(text):
    match = re.search(r"(\d+\.?\d*)\s*%\s*escalation", text, re.I)
    return float(match.group(1)) if match else 0

def extract_land_lease(text):
    rows = []

    date_pattern = r"([0-9]{1,2}\s+\w+\s+[0-9]{4})"
    pattern = date_pattern + r"\s+to\s+" + date_pattern + r"\s*=\s*AED\s*([\d,\s]+)"

    matches = re.findall(pattern, text, re.I)

    for start, end, amount in matches:
        start_date = parse_date(start)
        end_date = parse_date(end)

        if start_date and end_date:
            rows.append({
                "Type": "Land Lease",
                "Start Date": start_date,
                "End Date": end_date,
                "Amount": clean_amount(amount),
                "Volume": 0,
                "Rate": 0,
                "Escalation %": 0,
                "Remarks": "Fixed revenue period"
            })

    escalation = extract_escalation(text)

    if escalation > 0 and rows:
        last_row = rows[-1]
        escalation_start = last_row["End Date"] + pd.Timedelta(days=1)
        escalation_amount = last_row["Amount"]

        rows.append({
            "Type": "Land Lease Escalation",
            "Start Date": escalation_start,
            "End Date": datetime(escalation_start.year + 30, escalation_start.month, escalation_start.day),
            "Amount": escalation_amount,
            "Volume": 0,
            "Rate": 0,
            "Escalation %": escalation,
            "Remarks": f"{escalation}% escalation year on year on previous year"
        })

    return rows

def extract_throughput_volumes(text):
    rows = []

    date_pattern = r"([0-9]{1,2}\s+\w+\s+[0-9]{4})"
    pattern = r"([\d.]+)\s*Million\s+tons?\s+from\s+" + date_pattern + r"\s+to\s+" + date_pattern

    matches = re.findall(pattern, text, re.I)

    default_rate = extract_default_rate(text)
    escalation = extract_escalation(text)

    for volume, start, end in matches:
        start_date = parse_date(start)
        end_date = parse_date(end)

        if start_date and end_date:
            volume_tons = float(volume) * 1000000
            amount = volume_tons * default_rate if default_rate else 0

            rows.append({
                "Type": "Throughput",
                "Start Date": start_date,
                "End Date": end_date,
                "Amount": amount,
                "Volume": volume_tons,
                "Rate": default_rate,
                "Escalation %": escalation,
                "Remarks": "Volume commitment revenue"
            })

    return rows

def extract_default_rate(text):
    match = re.search(r"Up to\s+[\d.]+\s*Million\s+tons?\s*[:=]\s*AED\s*([\d.]+)", text, re.I)
    if match:
        return float(match.group(1))

    match = re.search(r"AED\s*([\d.]+)\s*per\s*Ton", text, re.I)
    if match:
        return float(match.group(1))

    return 0

def extract_rate_slabs(text):
    rows = []

    pattern = r"(Up to\s+[\d.]+\s*Million\s+tons?|[\d.]+\s+to\s+[\d.]+\s*Million\s+tons?)\s*[:=]\s*AED\s*([\d.]+)\s*per\s*Ton"

    matches = re.findall(pattern, text, re.I)

    for slab, rate in matches:
        rows.append({
            "Slab": slab,
            "Rate": float(rate),
            "Remarks": "Product handling rate slab"
        })

    return rows

def build_projection(terms, start_year, end_year):
    projection = []

    for quarter, q_start, q_end in quarter_ranges(start_year, end_year):
        land_lease = 0
        throughput = 0
        logic = []

        for term in terms:
            days = get_overlap_days(term["Start Date"], term["End Date"], q_start, q_end)

            if days > 0:
                total_days = (term["End Date"] - term["Start Date"]).days + 1
                base_value = term["Amount"] * days / total_days

                if term["Escalation %"] > 0:
                    years_passed = max(0, q_start.year - term["Start Date"].year)
                    value = base_value * ((1 + term["Escalation %"] / 100) ** years_passed)
                else:
                    value = base_value

                if "Land Lease" in term["Type"]:
                    land_lease += value
                elif term["Type"] == "Throughput":
                    throughput += value

                logic.append(
                    f"{term['Type']} = {round(term['Amount'],2)} × {days}/{total_days}"
                )

        projection.append({
            "Quarter": quarter,
            "Quarter Start": q_start.date(),
            "Quarter End": q_end.date(),
            "Land Lease Revenue": round(land_lease, 2),
            "Throughput Revenue": round(throughput, 2),
            "Total Revenue": round(land_lease + throughput, 2),
            "Calculation Logic": " | ".join(logic)
        })

    return pd.DataFrame(projection)

if uploaded_file:
    raw_text = extract_pdf_text(uploaded_file)
    text = clean_text(raw_text)

    st.success("PDF Text Extracted Successfully!")

    with st.expander("View Extracted Contract Text"):
        st.text_area("Contract Content", raw_text, height=300)

    effective_date = extract_effective_date(text)
    total_area = extract_area(text)
    escalation = extract_escalation(text)

    st.subheader("Contract Header")
    header_df = pd.DataFrame([{
        "Effective Date": effective_date.date() if effective_date else "",
        "Total Area Sq.m": total_area if total_area else "",
        "Escalation %": escalation
    }])
    st.dataframe(header_df)

    terms = []
    terms.extend(extract_land_lease(text))
    terms.extend(extract_throughput_volumes(text))

    terms_df = pd.DataFrame(terms)

    st.subheader("Extracted Contract Terms")
    edited_terms_df = st.data_editor(terms_df, num_rows="dynamic")

    rate_slabs = extract_rate_slabs(text)
    rate_slabs_df = pd.DataFrame(rate_slabs)

    st.subheader("Extracted Throughput Rate Slabs")
    st.dataframe(rate_slabs_df)

    st.subheader("Projection Settings")
    col1, col2 = st.columns(2)

    with col1:
        start_year = st.number_input("Start Year", value=2024)

    with col2:
        end_year = st.number_input("End Year", value=2035)

    projection_df = build_projection(
        edited_terms_df.to_dict("records"),
        int(start_year),
        int(end_year)
    )

    st.subheader("Quarterly Revenue Projection")
    st.dataframe(projection_df)

    yearly_df = projection_df.copy()
    yearly_df["Year"] = yearly_df["Quarter"].str[-4:]

    yearly_summary = yearly_df.groupby("Year")[[
        "Land Lease Revenue",
        "Throughput Revenue",
        "Total Revenue"
    ]].sum().reset_index()

    st.subheader("Yearly Revenue Projection")
    st.dataframe(yearly_summary)

    output = BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        header_df.to_excel(writer, index=False, sheet_name="Contract Header")
        edited_terms_df.to_excel(writer, index=False, sheet_name="Extracted Terms")
        rate_slabs_df.to_excel(writer, index=False, sheet_name="Rate Slabs")
        projection_df.to_excel(writer, index=False, sheet_name="Quarterly Projection")
        yearly_summary.to_excel(writer, index=False, sheet_name="Yearly Projection")

    output.seek(0)

    st.download_button(
        "Download Full Projection Excel",
        data=output,
        file_name="contract_revenue_projection.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
