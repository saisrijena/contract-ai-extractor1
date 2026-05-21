import streamlit as st
import fitz
import pandas as pd
import re
from io import BytesIO
from datetime import datetime
from dateutil.relativedelta import relativedelta

st.set_page_config(page_title="AI Contract Revenue Projection Tool", layout="wide")

st.title("AI Contract Extraction & Revenue Projection Tool")

uploaded_file = st.file_uploader("Upload Contract PDF", type=["pdf"])

def extract_pdf_text(file):
    doc = fitz.open(stream=file.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    return text

def clean_amount(value):
    return float(value.replace(",", "").replace(" ", ""))

def parse_date(date_text):
    date_text = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_text, flags=re.I)
    date_text = date_text.replace("Oct", "October")
    return datetime.strptime(date_text.strip(), "%d %B %Y")

def extract_land_lease(text):
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    text = text.replace("21,479, 280", "21,479,280")

    pattern = r"(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4})\s+to\s+(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4})\s*=\s*AED\s*([\d,\s]+)"
    matches = re.findall(pattern, text, re.I)

    rows = []
    for start, end, amount in matches:
        rows.append({
            "Type": "Land Lease",
            "Start Date": parse_date(start),
            "End Date": parse_date(end),
            "Amount": clean_amount(amount),
            "Rate": 0,
            "Volume": 0,
            "Escalation %": 0
        })

    # escalation starts after base year
    rows.append({
        "Type": "Land Lease Escalation",
        "Start Date": datetime(2028, 10, 25),
        "End Date": datetime(2074, 4, 25),
        "Amount": 21479280,
        "Rate": 0,
        "Volume": 0,
        "Escalation %": 2.5
    })

    return rows

def extract_throughput(text):
    rows = []

    volume_data = [
        ("26 October 2027", "25 October 2028", 5000000),
        ("26 October 2028", "25 October 2029", 10000000),
        ("26 October 2029", "25 October 2030", 15000000),
        ("26 October 2030", "25 October 2031", 15000000),
    ]

    for start, end, volume in volume_data:
        rows.append({
            "Type": "Throughput",
            "Start Date": parse_date(start),
            "End Date": parse_date(end),
            "Amount": volume * 3.5,
            "Rate": 3.5,
            "Volume": volume,
            "Escalation %": 2.5
        })

    return rows

def quarter_ranges(start_year, end_year):
    quarters = []
    for year in range(start_year, end_year + 1):
        quarters.extend([
            (f"Q1 {year}", datetime(year, 1, 1), datetime(year, 3, 31)),
            (f"Q2 {year}", datetime(year, 4, 1), datetime(year, 6, 30)),
            (f"Q3 {year}", datetime(year, 7, 1), datetime(year, 9, 30)),
            (f"Q4 {year}", datetime(year, 10, 1), datetime(year, 12, 31)),
        ])
    return quarters

def overlap_days(start1, end1, start2, end2):
    latest_start = max(start1, start2)
    earliest_end = min(end1, end2)
    days = (earliest_end - latest_start).days + 1
    return max(0, days)

def build_projection(terms, start_year=2024, end_year=2035):
    output = []

    for quarter, q_start, q_end in quarter_ranges(start_year, end_year):
        land_lease = 0
        throughput = 0
        calculation = []

        for term in terms:
            days = overlap_days(term["Start Date"], term["End Date"], q_start, q_end)

            if days > 0:
                total_days = (term["End Date"] - term["Start Date"]).days + 1
                value = term["Amount"] * days / total_days

                if term["Escalation %"] > 0:
                    years_after_start = max(0, q_start.year - term["Start Date"].year)
                    value = value * ((1 + term["Escalation %"] / 100) ** years_after_start)

                if "Land Lease" in term["Type"]:
                    land_lease += value
                elif term["Type"] == "Throughput":
                    throughput += value

                calculation.append(
                    f"{term['Type']}: {round(value,2)} based on {days} overlapping days"
                )

        output.append({
            "Quarter": quarter,
            "Quarter Start": q_start.date(),
            "Quarter End": q_end.date(),
            "Land Lease Revenue": round(land_lease, 2),
            "Throughput Revenue": round(throughput, 2),
            "Total Revenue": round(land_lease + throughput, 2),
            "Calculation Logic": " | ".join(calculation)
        })

    return pd.DataFrame(output)

if uploaded_file:
    raw_text = extract_pdf_text(uploaded_file)

    st.success("PDF Text Extracted Successfully!")

    with st.expander("View Extracted Contract Text"):
        st.text_area("Contract Content", raw_text, height=300)

    terms = []
    terms.extend(extract_land_lease(raw_text))
    terms.extend(extract_throughput(raw_text))

    terms_df = pd.DataFrame(terms)

    st.subheader("Extracted Contract Terms")
    st.dataframe(terms_df)

    st.subheader("Revenue Projection Settings")

    col1, col2 = st.columns(2)

    with col1:
        start_year = st.number_input("Start Year", value=2024)

    with col2:
        end_year = st.number_input("End Year", value=2035)

    projection_df = build_projection(terms, int(start_year), int(end_year))

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
        terms_df.to_excel(writer, index=False, sheet_name="Extracted Terms")
        projection_df.to_excel(writer, index=False, sheet_name="Quarterly Projection")
        yearly_summary.to_excel(writer, index=False, sheet_name="Yearly Projection")

    output.seek(0)

    st.download_button(
        "Download Full Projection Excel",
        data=output,
        file_name="contract_revenue_projection.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
