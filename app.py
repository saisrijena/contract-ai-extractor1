import streamlit as st
import fitz
import pandas as pd
import re
from io import BytesIO
from datetime import datetime, timedelta

st.set_page_config(page_title="Land Lease Revenue Engine", layout="wide")
st.title("Land Lease Revenue Projection Engine")

uploaded_file = st.file_uploader("Upload Contract PDF", type=["pdf"])

# ---------- BASIC FUNCTIONS ----------

def extract_pdf_text(file):
    doc = fitz.open(stream=file.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text("text") + "\n"
    return text

def normalize_text(text):
    text = text.replace("\n", " ")
    text = text.replace("\t", " ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(\d),\s+(\d)", r"\1,\2", text)
    text = text.replace("Oct ", "October ")
    text = text.replace("Sep ", "September ")
    text = text.replace("Sept ", "September ")
    return text.strip()

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

def clean_number(value):
    return float(str(value).replace(",", "").replace(" ", ""))

def to_mn(value):
    return round(float(value) / 1_000_000, 2)

def overlap_days(start1, end1, start2, end2):
    start = max(start1, start2)
    end = min(end1, end2)
    return max(0, (end - start).days + 1)

# ---------- LAND LEASE EXTRACTION ----------

def get_land_lease_section(text):
    cleaned = normalize_text(text)

    if "Land Lease" in cleaned and "Throughput" in cleaned:
        return cleaned.split("Land Lease", 1)[1].split("Throughput", 1)[0]

    return cleaned

def extract_area(section):
    match = re.search(r"Total Area\s*[:\-]?\s*([\d,]+)\s*Sq", section, re.I)
    return clean_number(match.group(1)) if match else 0

def extract_fixed_and_area_rows(section):
    rows = []
    area = extract_area(section)

    date_regex = r"\d{1,2}\s*(?:st|nd|rd|th)?\s+\w+\s+\d{4}"

    pattern = rf"""
    ({date_regex})
    \s*to\s*
    ({date_regex})
    \s*=\s*AED\s*
    ([0-9][0-9,\s]*[0-9])
    """

    matches = list(re.finditer(pattern, section, re.I | re.X))

    for m in matches:
        start = parse_date(m.group(1))
        end = parse_date(m.group(2))

        if not start or not end:
            continue

        amount_text = m.group(3)
        amount_text = re.split(r"\s+\d{1,2}\s*(?:st|nd|rd|th)?\s+\w+\s+\d{4}", amount_text)[0]
        amount_text = re.split(r"\s+From\s+", amount_text, flags=re.I)[0]
        amount_text = re.sub(r"\s+", "", amount_text)

        amount = clean_number(amount_text)

        row_context = section[m.start():m.end() + 120]
        rate_match = re.search(r"\(AED\s*([\d.]+)\s*[xX]\s*([\d,]+)", row_context, re.I)

        if rate_match:
            rate = float(rate_match.group(1))
            amount = rate * area
            charge_type = "Area Based Revenue"
            calculation_basis = f"AED {rate} × {int(area)} sqm"
        else:
            rate = 0
            charge_type = "Fixed Revenue"
            calculation_basis = "Fixed amount for specific period"

        rows.append({
            "Revenue Type": "Land Lease",
            "Start Date": start,
            "End Date": end,
            "Charge Type": charge_type,
            "Area Sqm": area,
            "Rate AED/Sqm": rate,
            "Amount AED": amount,
            "Amount AED Mn": to_mn(amount),
            "Escalation %": 0,
            "Calculation Basis": calculation_basis
        })

    return rows

def extract_escalation_info(section):
    pattern = r"""
    From\s*
    (\d{1,2}\s*(?:st|nd|rd|th)?\s+\w+\s+\d{4})
    \s*to\s*
    (\d{1,2}\s*(?:st|nd|rd|th)?\s+\w+\s+\d{4})
    .*?
    (\d+\.?\d*)\s*%
    """

    match = re.search(pattern, section, re.I | re.X)

    if not match:
        return None

    return {
        "Start Date": parse_date(match.group(1)),
        "End Date": parse_date(match.group(2)),
        "Escalation %": float(match.group(3))
    }

def build_land_lease_terms(section):
    rows = extract_fixed_and_area_rows(section)
    escalation = extract_escalation_info(section)

    if escalation and rows:
        last_row = rows[-1]
        esc_start = escalation["Start Date"]
        esc_end = datetime(esc_start.year + 30, esc_start.month, esc_start.day)

        rows.append({
            "Revenue Type": "Land Lease",
            "Start Date": esc_start,
            "End Date": esc_end,
            "Charge Type": "Escalated Revenue",
            "Area Sqm": last_row["Area Sqm"],
            "Rate AED/Sqm": last_row["Rate AED/Sqm"],
            "Amount AED": last_row["Amount AED"],
            "Amount AED Mn": to_mn(last_row["Amount AED"]),
            "Escalation %": escalation["Escalation %"],
            "Calculation Basis": f"Previous year revenue escalated by {escalation['Escalation %']}% YoY"
        })

    return rows

# ---------- PROJECTION ENGINE ----------

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

def get_escalated_annual_amount(term, q_start):
    base_amount = term["Amount AED"]

    if term["Escalation %"] > 0:
        years_passed = max(0, q_start.year - term["Start Date"].year)
        return base_amount * ((1 + term["Escalation %"] / 100) ** years_passed)

    return base_amount

def build_quarterly_projection(terms, start_year, end_year):
    output = []

    for quarter, q_start, q_end in quarter_ranges(start_year, end_year):
        revenue = 0
        logic = []

        for term in terms:
            days = overlap_days(term["Start Date"], term["End Date"], q_start, q_end)

            if days <= 0:
                continue

            total_days = (term["End Date"] - term["Start Date"]).days + 1
            period_value = get_escalated_annual_amount(term, q_start)
            quarter_value = period_value * days / total_days

            revenue += quarter_value

            logic.append(
                f"{term['Charge Type']}: AED {to_mn(quarter_value)} Mn = "
                f"AED {to_mn(period_value)} Mn × {days}/{total_days}"
            )

        output.append({
            "Quarter": quarter,
            "Quarter Start": q_start.date(),
            "Quarter End": q_end.date(),
            "Land Lease Revenue AED Mn": to_mn(revenue),
            "Calculation Logic": " | ".join(logic)
        })

    return pd.DataFrame(output)

# ---------- APP ----------

if uploaded_file:
    raw_text = extract_pdf_text(uploaded_file)

    st.success("PDF Text Extracted Successfully")

    with st.expander("View Extracted Contract Text"):
        st.text_area("Contract Content", raw_text, height=300)

    land_section = get_land_lease_section(raw_text)

    with st.expander("View Land Lease Section"):
        st.text_area("Land Lease Section", land_section, height=250)

    terms = build_land_lease_terms(land_section)

    if not terms:
        st.error("No land lease terms extracted. Please check contract format.")
        st.stop()

    terms_df = pd.DataFrame(terms)

    st.subheader("Extracted Land Lease Terms")
    edited_terms_df = st.data_editor(terms_df, num_rows="dynamic")

    st.subheader("Projection Settings")

    min_year = int(edited_terms_df["Start Date"].dt.year.min())

    col1, col2 = st.columns(2)

    with col1:
        start_year = st.number_input("Start Calendar Year", value=min_year)

    with col2:
        end_year = st.number_input("End Calendar Year", value=min_year + 15)

    projection_df = build_quarterly_projection(
        edited_terms_df.to_dict("records"),
        int(start_year),
        int(end_year)
    )

    st.subheader("Quarterly Land Lease Revenue Projection")
    st.dataframe(projection_df, use_container_width=True, height=500)

    st.subheader("Detailed Calculation Logic")

    selected_quarter = st.selectbox(
        "Select Quarter",
        projection_df["Quarter"]
    )

    selected_row = projection_df[
        projection_df["Quarter"] == selected_quarter
    ].iloc[0]

    st.text_area(
        "Calculation Logic",
        selected_row["Calculation Logic"],
        height=250
    )

    yearly_df = projection_df.copy()
    yearly_df["Calendar Year"] = yearly_df["Quarter"].str[-4:]

    calendar_year_df = yearly_df.groupby("Calendar Year")[[
        "Land Lease Revenue AED Mn"
    ]].sum().reset_index()

    calendar_year_df["Land Lease Revenue AED Mn"] = calendar_year_df[
        "Land Lease Revenue AED Mn"
    ].round(2)

    st.subheader("Calendar Year Land Lease Revenue")
    st.dataframe(calendar_year_df, use_container_width=True)

    output = BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        edited_terms_df.to_excel(writer, index=False, sheet_name="Extracted Land Lease")
        projection_df.to_excel(writer, index=False, sheet_name="Quarterly Projection")
        calendar_year_df.to_excel(writer, index=False, sheet_name="Calendar Year Revenue")

    output.seek(0)

    st.download_button(
        "Download Land Lease Projection Excel",
        data=output,
        file_name="land_lease_revenue_projection.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
