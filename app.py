import streamlit as st
import fitz
import pandas as pd
import re
from io import BytesIO
from datetime import datetime, timedelta

st.set_page_config(page_title="Land Lease Revenue Engine", layout="wide")
st.title("Land Lease Revenue Projection Engine")

uploaded_file = st.file_uploader("Upload Contract PDF", type=["pdf"])

# ---------------- BASIC FUNCTIONS ----------------

def extract_pdf_text(file):
    doc = fitz.open(stream=file.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text("text") + "\n"
    return text

def extract_land_lease_rows(section):
    rows = []

    section = normalize_text(section)
    area = extract_area(section)

    date_regex = r"\d{1,2}\s*(?:st|nd|rd|th)?\s+\w+\s+\d{4}"

    period_pattern = rf"(?:From\s*)?({date_regex})\s*to\s*({date_regex})"
    period_matches = list(re.finditer(period_pattern, section, re.I))

    for index, match in enumerate(period_matches):
        start_text = match.group(1)
        end_text = match.group(2)

        start_date = parse_date(start_text)
        end_date = parse_date(end_text)

        if not start_date or not end_date:
            continue

        segment_start = match.start()
        segment_end = period_matches[index + 1].start() if index + 1 < len(period_matches) else len(section)
        segment = section[segment_start:segment_end]

        # Skip escalation line like AED 2.5% escalation
        if re.search(r"AED\s*\d+\.?\d*\s*%", segment, re.I):
            continue

        # Detect area-based logic: AED 60 X 357,988
        rate_match = re.search(
            r"AED\s*([\d.]+)\s*X\s*([\d,]+)",
            segment,
            re.I
        )

        # Extract amount after = AED, but do not stop at broken comma
        amount_match = re.search(
            r"=\s*AED\s*([0-9][0-9,\s]*[0-9])",
            segment,
            re.I
        )

        if not amount_match and not rate_match:
            continue

        if rate_match:
            rate = float(rate_match.group(1))
            area_from_formula = clean_number(rate_match.group(2))
            final_area = area if area > 0 else area_from_formula

            amount = rate * final_area

            charge_type = "Area Based Revenue"
            calculation_basis = f"AED {rate} × {int(final_area)} sqm"

        else:
            rate = 0
            final_area = area

            amount_text = amount_match.group(1)

            # Clean amount safely
            amount_text = re.sub(r"\s+", "", amount_text)
            amount = clean_number(amount_text)

            charge_type = "Fixed Revenue"
            calculation_basis = "Fixed amount for specific period"

        rows.append({
            "Revenue Type": "Land Lease",
            "Start Date": start_date,
            "End Date": end_date,
            "Charge Type": charge_type,
            "Area Sqm": final_area,
            "Rate AED/Sqm": rate,
            "Amount AED": amount,
            "Amount AED Mn": to_mn(amount),
            "Escalation %": 0,
            "Calculation Basis": calculation_basis
        })

    rows = sorted(rows, key=lambda x: x["Start Date"])

    return rows
def parse_date(text):
    text = str(text).strip()
    text = re.sub(r"(\d+)\s*(st|nd|rd|th)", r"\1", text, flags=re.I)

    month_map = {
        "Jan": "January",
        "Feb": "February",
        "Mar": "March",
        "Apr": "April",
        "Jun": "June",
        "Jul": "July",
        "Aug": "August",
        "Sep": "September",
        "Sept": "September",
        "Oct": "October",
        "Nov": "November",
        "Dec": "December",
    }

    for short, full in month_map.items():
        text = re.sub(rf"\b{short}\b", full, text, flags=re.I)

    text = re.sub(r"\s+", " ", text).strip()

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

def add_years(date_value, years):
    try:
        return date_value.replace(year=date_value.year + years)
    except ValueError:
        return date_value.replace(month=2, day=28, year=date_value.year + years)

def overlap_days(start1, end1, start2, end2):
    start = max(start1, start2)
    end = min(end1, end2)
    return max(0, (end - start).days + 1)

def ensure_datetime(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    return pd.to_datetime(value).to_pydatetime()

# ---------------- LAND LEASE EXTRACTION ----------------

def get_land_lease_section(text):
    cleaned = normalize_text(text)

    match = re.search(
        r"Land\s+Lease\s*:?(.*?)(?:Throughput|Commercial Operations|Volume Commitments|Product Handling|$)",
        cleaned,
        re.I
    )

    if match:
        return match.group(1).strip()

    return cleaned

def extract_area(section):
    section = normalize_text(section)
    match = re.search(r"Total Area\s*[:\-]?\s*([\d,]+)\s*Sq", section, re.I)

    if match:
        return clean_number(match.group(1))

    # fallback: find area inside AED 60 X 357,988
    match = re.search(r"AED\s*[\d.]+\s*X\s*([\d,]+)", section, re.I)

    if match:
        return clean_number(match.group(1))

    return 0

def extract_escalation_info(section):
    section = normalize_text(section)

    date_regex = r"\d{1,2}\s*(?:st|nd|rd|th)?\s+\w+\s+\d{4}"

    pattern = rf"""
    From\s*
    ({date_regex})
    \s*to\s*
    ({date_regex})
    .*?
    (\d+\.?\d*)\s*%
    """

    match = re.search(pattern, section, re.I | re.X)

    if match:
        return {
            "Start Date": parse_date(match.group(1)),
            "End Date": parse_date(match.group(2)),
            "Escalation %": float(match.group(3))
        }

    percent_match = re.search(r"(\d+\.?\d*)\s*%\s*escalation", section, re.I)

    if percent_match:
        return {
            "Start Date": None,
            "End Date": None,
            "Escalation %": float(percent_match.group(1))
        }

    return None

def extract_land_lease_rows(section):
    rows = []

    section = normalize_text(section)
    area = extract_area(section)

    date_regex = r"\d{1,2}\s*(?:st|nd|rd|th)?\s+\w+\s+\d{4}"

    # Find every date-to-date period
    period_pattern = rf"(?:From\s*)?({date_regex})\s*to\s*({date_regex})"
    period_matches = list(re.finditer(period_pattern, section, re.I))

    for index, match in enumerate(period_matches):
        start_text = match.group(1)
        end_text = match.group(2)

        start_date = parse_date(start_text)
        end_date = parse_date(end_text)

        if not start_date or not end_date:
            continue

        segment_start = match.start()
        segment_end = period_matches[index + 1].start() if index + 1 < len(period_matches) else len(section)
        segment = section[segment_start:segment_end]

        # Skip escalation line like AED 2.5% escalation
        if re.search(r"AED\s*\d+\.?\d*\s*%", segment, re.I):
            continue

        # Detect rate logic: (AED 60 X 357,988)
        rate_match = re.search(r"AED\s*([\d.]+)\s*X\s*([\d,]+)", segment, re.I)

        # Detect amount after = AED
        amount_match = re.search(
            r"=\s*AED\s*([0-9]{1,3}(?:,\s*[0-9]{3})+|[0-9]+)",
            segment,
            re.I
        )

        if not amount_match and not rate_match:
            continue

        if rate_match:
            rate = float(rate_match.group(1))
            area_from_formula = clean_number(rate_match.group(2))
            final_area = area if area > 0 else area_from_formula
            amount = rate * final_area

            charge_type = "Area Based Revenue"
            calculation_basis = f"AED {rate} × {int(final_area)} sqm"
        else:
            rate = 0
            final_area = area
            amount = clean_number(amount_match.group(1))

            charge_type = "Fixed Revenue"
            calculation_basis = "Fixed amount for specific period"

        rows.append({
            "Revenue Type": "Land Lease",
            "Start Date": start_date,
            "End Date": end_date,
            "Charge Type": charge_type,
            "Area Sqm": final_area,
            "Rate AED/Sqm": rate,
            "Amount AED": amount,
            "Amount AED Mn": to_mn(amount),
            "Escalation %": 0,
            "Calculation Basis": calculation_basis
        })

    rows = sorted(rows, key=lambda x: x["Start Date"])

    return rows

def build_land_lease_terms(section, escalation_years=30):
    rows = extract_land_lease_rows(section)
    escalation = extract_escalation_info(section)

    if escalation and rows:
        last_row = rows[-1]

        escalation_percent = escalation["Escalation %"]
        escalation_start = escalation["Start Date"]

        if escalation_start is None:
            escalation_start = last_row["End Date"] + timedelta(days=1)

        base_amount = last_row["Amount AED"]
        base_rate = last_row["Rate AED/Sqm"]
        area = last_row["Area Sqm"]

        current_start = escalation_start

        for year_no in range(1, escalation_years + 1):
            current_end = add_years(current_start, 1) - timedelta(days=1)

            escalated_amount = base_amount * ((1 + escalation_percent / 100) ** year_no)

            if base_rate > 0:
                escalated_rate = base_rate * ((1 + escalation_percent / 100) ** year_no)
                calculation_basis = f"AED {round(escalated_rate, 2)} × {int(area)} sqm"
            else:
                escalated_rate = 0
                calculation_basis = f"Previous year revenue escalated by {escalation_percent}%"

            rows.append({
                "Revenue Type": "Land Lease",
                "Start Date": current_start,
                "End Date": current_end,
                "Charge Type": "Escalated Revenue",
                "Area Sqm": area,
                "Rate AED/Sqm": round(escalated_rate, 2),
                "Amount AED": escalated_amount,
                "Amount AED Mn": to_mn(escalated_amount),
                "Escalation %": escalation_percent,
                "Calculation Basis": calculation_basis
            })

            current_start = current_end + timedelta(days=1)

    return rows

# ---------------- PROJECTION ENGINE ----------------

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

def build_quarterly_projection(terms, start_year, end_year):
    output = []

    for quarter, q_start, q_end in quarter_ranges(start_year, end_year):
        revenue = 0
        logic = []

        for term in terms:
            term_start = ensure_datetime(term["Start Date"])
            term_end = ensure_datetime(term["End Date"])

            days = overlap_days(term_start, term_end, q_start, q_end)

            if days <= 0:
                continue

            total_days = (term_end - term_start).days + 1
            period_amount = float(term["Amount AED"])
            quarter_value = period_amount * days / total_days

            revenue += quarter_value

            logic.append(
                f"{term['Charge Type']}: AED {to_mn(quarter_value)} Mn = "
                f"AED {to_mn(period_amount)} Mn × {days}/{total_days}. "
                f"Basis: {term['Calculation Basis']}"
            )

        output.append({
            "Quarter": quarter,
            "Quarter Start": q_start.date(),
            "Quarter End": q_end.date(),
            "Land Lease Revenue AED Mn": to_mn(revenue),
            "Calculation Logic": " | ".join(logic)
        })

    return pd.DataFrame(output)

# ---------------- APP ----------------

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

    edited_terms_df = st.data_editor(
        terms_df,
        num_rows="dynamic",
        use_container_width=True,
        height=450
    )

    st.subheader("Projection Settings")

    edited_terms_df["Start Date"] = pd.to_datetime(edited_terms_df["Start Date"])
    edited_terms_df["End Date"] = pd.to_datetime(edited_terms_df["End Date"])

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

    st.dataframe(
        projection_df,
        use_container_width=True,
        height=500
    )

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
