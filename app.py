import streamlit as st
import fitz
import pandas as pd
import re
from io import BytesIO
from datetime import datetime, timedelta

st.set_page_config(page_title="AI Contract Revenue Projection Tool", layout="wide")
st.title("AI Contract Extraction & Revenue Projection Tool")

uploaded_file = st.file_uploader("Upload Contract PDF", type=["pdf"])

def extract_pdf_text(file):
    doc = fitz.open(stream=file.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text() + "\n"
    return text

def normalize_text(text):
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(\d),\s+(\d)", r"\1,\2", text)
    return text

def parse_date(text):
    text = str(text).strip()
    text = re.sub(r"(\d+)\s*(st|nd|rd|th)", r"\1", text, flags=re.I)
    text = text.replace("Oct", "October")
    text = text.replace("Sept", "September")
    text = text.replace("Sep", "September")
    text = re.sub(r"\s+", " ", text)

    for fmt in ["%d %B %Y", "%d %b %Y"]:
        try:
            return datetime.strptime(text, fmt)
        except:
            pass
    return None

def clean_amount(x):
    return float(str(x).replace(",", "").replace(" ", ""))

def to_million(x):
    return round(float(x) / 1_000_000, 2)

def extract_escalation(text):
    m = re.search(r"(\d+\.?\d*)\s*%\s*escalation", text, re.I)
    return float(m.group(1)) if m else 0

def extract_land_lease(text):
    rows = []
    cleaned_text = normalize_text(text)

    pattern = r"(\d{1,2}\s*(?:st|nd|rd|th)?\s+\w+\s+\d{4})\s*to\s*(\d{1,2}\s*(?:st|nd|rd|th)?\s+\w+\s+\d{4})\s*=\s*AED\s*([\d,\s]+)"

    matches = re.findall(pattern, cleaned_text, re.I)

    for start_text, end_text, amount_text in matches:
        start = parse_date(start_text)
        end = parse_date(end_text)
        amount = clean_amount(amount_text)

        if start and end:
            rows.append({
                "Type": "Land Lease",
                "Start Date": start,
                "End Date": end,
                "Amount AED": amount,
                "Amount AED Mn": to_million(amount),
                "Volume": 0,
                "Rate": 0,
                "Escalation %": 0,
                "Remarks": "Fixed revenue period"
            })

    escalation = extract_escalation(text)

    if escalation > 0 and rows:
        last = rows[-1]
        esc_start = last["End Date"] + timedelta(days=1)

        rows.append({
            "Type": "Land Lease Escalation",
            "Start Date": esc_start,
            "End Date": datetime(esc_start.year + 30, esc_start.month, esc_start.day),
            "Amount AED": last["Amount AED"],
            "Amount AED Mn": to_million(last["Amount AED"]),
            "Volume": 0,
            "Rate": last["Rate"],
            "Escalation %": escalation,
            "Remarks": f"{escalation}% escalation year on year"
        })

    return rows

def extract_rate_slabs(text):
    cleaned_text = normalize_text(text)

    pattern = r"(Up to\s+[\d.]+\s*Million\s+tons?|[\d.]+\s+to\s+[\d.]+\s*Million\s+tons?)\s*[:=]\s*AED\s*([\d.]+)\s*per\s*Ton"

    matches = re.findall(pattern, cleaned_text, re.I)

    slabs = []

    for slab, rate in matches:
        slabs.append({
            "Volume Slab": slab,
            "Rate AED/Ton": float(rate)
        })

    return slabs

def get_default_rate(text):
    slabs = extract_rate_slabs(text)
    if slabs:
        return slabs[0]["Rate AED/Ton"]
    return 0

def extract_throughput(text):
    rows = []
    cleaned_text = normalize_text(text)

    default_rate = get_default_rate(text)
    escalation = extract_escalation(text)

    pattern = r"([\d.]+)\s*Million\s+tons?\s+from\s+(\d{1,2}\s*(?:st|nd|rd|th)?\s+\w+\s+\d{4})\s*to\s*(\d{1,2}\s*(?:st|nd|rd|th)?\s+\w+\s+\d{4})"

    matches = re.findall(pattern, cleaned_text, re.I)

    for volume_text, start_text, end_text in matches:
        start = parse_date(start_text)
        end = parse_date(end_text)

        if start and end:
            volume = float(volume_text) * 1_000_000
            amount = volume * default_rate if default_rate else 0

            rows.append({
                "Type": "Throughput",
                "Start Date": start,
                "End Date": end,
                "Amount AED": amount,
                "Amount AED Mn": to_million(amount),
                "Volume": volume,
                "Rate": default_rate,
                "Escalation %": escalation,
                "Remarks": "Volume commitment × product handling rate"
            })

    return rows

def quarter_ranges(start_year, end_year):
    quarters = []

    for y in range(start_year, end_year + 1):
        quarters.extend([
            (f"Q1 {y}", datetime(y, 1, 1), datetime(y, 3, 31)),
            (f"Q2 {y}", datetime(y, 4, 1), datetime(y, 6, 30)),
            (f"Q3 {y}", datetime(y, 7, 1), datetime(y, 9, 30)),
            (f"Q4 {y}", datetime(y, 10, 1), datetime(y, 12, 31)),
        ])

    return quarters

def overlap_days(start1, end1, start2, end2):
    latest_start = max(start1, start2)
    earliest_end = min(end1, end2)
    days = (earliest_end - latest_start).days + 1
    return max(0, days)

def calculate_escalated_value(term, q_start):
    value = term["Amount AED"]

    if term["Escalation %"] > 0:
        years_passed = max(0, q_start.year - term["Start Date"].year)
        value = value * ((1 + term["Escalation %"] / 100) ** years_passed)

    return value

def build_projection(terms, start_year, end_year):
    output = []

    for quarter, q_start, q_end in quarter_ranges(start_year, end_year):
        land = 0
        throughput = 0
        logic = []

        for term in terms:
            if pd.isna(term["Start Date"]) or pd.isna(term["End Date"]):
                continue

            days = overlap_days(term["Start Date"], term["End Date"], q_start, q_end)

            if days > 0:
                total_days = (term["End Date"] - term["Start Date"]).days + 1
                annual_or_period_amount = calculate_escalated_value(term, q_start)

                value = annual_or_period_amount * days / total_days

                if "Land Lease" in term["Type"]:
                    land += value
                elif term["Type"] == "Throughput":
                    throughput += value

                logic.append(
                    f"{term['Type']}: AED {to_million(value)} Mn = AED {to_million(annual_or_period_amount)} Mn × {days}/{total_days}"
                )

        output.append({
            "Quarter": quarter,
            "Quarter Start": q_start.date(),
            "Quarter End": q_end.date(),
            "Land Lease Revenue AED Mn": to_million(land),
            "Throughput Revenue AED Mn": to_million(throughput),
            "Total Revenue AED Mn": to_million(land + throughput),
            "Calculation Logic": " | ".join(logic)
        })

    return pd.DataFrame(output)

if uploaded_file:
    raw_text = extract_pdf_text(uploaded_file)

    st.success("PDF Text Extracted Successfully!")

    with st.expander("View Extracted Contract Text"):
        st.text_area("Contract Content", raw_text, height=300)

    land_terms = extract_land_lease(raw_text)
    throughput_terms = extract_throughput(raw_text)
    all_terms = land_terms + throughput_terms

    if not all_terms:
        st.error("No contract terms extracted. Please check PDF text format.")
        st.stop()

    terms_df = pd.DataFrame(all_terms)

    st.subheader("Extracted Contract Terms")
    edited_terms_df = st.data_editor(terms_df, num_rows="dynamic")

    slabs = extract_rate_slabs(raw_text)
    slabs_df = pd.DataFrame(slabs)

    st.subheader("Extracted Throughput Rate Slabs")
    st.dataframe(slabs_df)

    st.subheader("Projection Settings")

    min_year = int(edited_terms_df["Start Date"].dt.year.min())
    max_year = int(edited_terms_df["End Date"].dt.year.max())

    col1, col2 = st.columns(2)

    with col1:
        start_year = st.number_input("Start Calendar Year", value=min_year)

    with col2:
        end_year = st.number_input("End Calendar Year", value=min(max_year, min_year + 15))

    projection_df = build_projection(
        edited_terms_df.to_dict("records"),
        int(start_year),
        int(end_year)
    )

    st.subheader("Quarterly Revenue Projection")
    st.dataframe(projection_df)

    yearly_summary = projection_df.copy()
    yearly_summary["Calendar Year"] = yearly_summary["Quarter"].str[-4:]

    yearly_summary = yearly_summary.groupby("Calendar Year")[[
        "Land Lease Revenue AED Mn",
        "Throughput Revenue AED Mn",
        "Total Revenue AED Mn"
    ]].sum().reset_index()

    yearly_summary[[
        "Land Lease Revenue AED Mn",
        "Throughput Revenue AED Mn",
        "Total Revenue AED Mn"
    ]] = yearly_summary[[
        "Land Lease Revenue AED Mn",
        "Throughput Revenue AED Mn",
        "Total Revenue AED Mn"
    ]].round(2)

    st.subheader("Calendar Year Revenue Projection")
    st.dataframe(yearly_summary)

    output = BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        edited_terms_df.to_excel(writer, index=False, sheet_name="Extracted Terms")
        slabs_df.to_excel(writer, index=False, sheet_name="Rate Slabs")
        projection_df.to_excel(writer, index=False, sheet_name="Quarterly Projection")
        yearly_summary.to_excel(writer, index=False, sheet_name="Calendar Year Revenue")

    output.seek(0)

    st.download_button(
        "Download Full Projection Excel",
        data=output,
        file_name="contract_revenue_projection.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
