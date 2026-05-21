import streamlit as st
import fitz
import pandas as pd
import re
from io import BytesIO
from datetime import datetime, timedelta
from docx import Document
from dateutil.relativedelta import relativedelta
from dateutil.parser import parse as date_parse

st.set_page_config(page_title="Land Lease Revenue Engine", layout="wide")
st.title("Land Lease Revenue Projection Engine")

uploaded_file = st.file_uploader(
    "Upload Contract File",
    type=["pdf", "docx", "txt"]
)

# --------------------------------------------------
# FILE READING
# --------------------------------------------------

def extract_pdf_text(file):
    doc = fitz.open(stream=file.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text("text") + "\n"
    return text


def extract_docx_text(file):
    document = Document(file)
    text = ""
    for para in document.paragraphs:
        text += para.text + "\n"
    return text


def extract_txt_text(file):
    return file.read().decode("utf-8", errors="ignore")


def extract_file_text(file):
    name = file.name.lower()

    if name.endswith(".pdf"):
        return extract_pdf_text(file)

    if name.endswith(".docx"):
        return extract_docx_text(file)

    if name.endswith(".txt"):
        return extract_txt_text(file)

    return ""


# --------------------------------------------------
# BASIC HELPERS
# --------------------------------------------------

DAY_FIRST_DATE = r"\d{1,2}\s*(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}"
MONTH_FIRST_DATE = r"[A-Za-z]+\s+\d{1,2},?\s*\d{4}"
DATE_REGEX = rf"(?:{DAY_FIRST_DATE}|{MONTH_FIRST_DATE})"


def normalize_text(text):
    text = str(text)

    text = text.replace("\n", " ")
    text = text.replace("\t", " ")
    text = text.replace("×", "X")

    # 26 th -> 26th
    text = re.sub(r"(\d+)\s+(st|nd|rd|th)", r"\1\2", text, flags=re.I)

    # 21,479, 280 -> 21,479,280
    text = re.sub(r"(\d),\s+(\d)", r"\1,\2", text)

    text = re.sub(r"\s+", " ", text)

    month_map = {
        "Jan": "January",
        "Feb": "February",
        "Mar": "March",
        "Apr": "April",
        "Jun": "June",
        "Jul": "July",
        "Aug": "August",
        "Sept": "September",
        "Sep": "September",
        "Oct": "October",
        "Nov": "November",
        "Dec": "December",
    }

    for short, full in month_map.items():
        text = re.sub(rf"\b{short}\b", full, text, flags=re.I)

    return text.strip()


def parse_date(text):
    if not text:
        return None

    text = str(text).strip()
    text = re.sub(r"(\d+)\s*(st|nd|rd|th)", r"\1", text, flags=re.I)
    text = normalize_text(text)

    formats = [
        "%d %B %Y",
        "%B %d, %Y",
        "%B %d %Y",
        "%Y-%m-%d",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass

    try:
        return date_parse(text, fuzzy=True, dayfirst=True)
    except Exception:
        return None


def clean_number(value):
    value = str(value)
    value = value.replace(",", "")
    value = value.replace(" ", "")
    return float(value)


def to_mn(value):
    return round(float(value) / 1_000_000, 2)


def add_years(date_value, years):
    try:
        return date_value.replace(year=date_value.year + years)
    except ValueError:
        return date_value.replace(month=2, day=28, year=date_value.year + years)


def ensure_datetime(value):
    if isinstance(value, datetime):
        return value

    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()

    return pd.to_datetime(value).to_pydatetime()


def overlap_days(start1, end1, start2, end2):
    start = max(start1, start2)
    end = min(end1, end2)
    return max(0, (end - start).days + 1)


def annual_period_days(start_date):
    return (add_years(start_date, 1) - start_date).days


def period_amount_from_annual_rate(start_date, end_date, rate, area):
    days = (end_date - start_date).days + 1
    annual_days = annual_period_days(start_date)
    return rate * area * days / annual_days


# --------------------------------------------------
# HEADER EXTRACTION
# --------------------------------------------------

def extract_date_after_label(text, label):
    cleaned = normalize_text(text)

    pattern = rf"{label}\s*[:\-]?\s*({DATE_REGEX})"
    match = re.search(pattern, cleaned, re.I)

    if match:
        return parse_date(match.group(1))

    # fallback: take short text after label and try fuzzy date parsing
    label_match = re.search(label, cleaned, re.I)
    if label_match:
        snippet = cleaned[label_match.end():label_match.end() + 80]
        date_match = re.search(DATE_REGEX, snippet, re.I)
        if date_match:
            return parse_date(date_match.group(0))

    return None


def extract_effective_date(text):
    return extract_date_after_label(text, r"Effective\s*Date")


def extract_handover_date(text):
    return extract_date_after_label(text, r"Handover\s*Date")


def extract_contract_term_years(text):
    cleaned = normalize_text(text)

    match = re.search(
        r"Contract Term\s*[:\-]?\s*(\d+)\s*years?",
        cleaned,
        re.I
    )

    if match:
        return int(match.group(1))

    return None


def calculate_contract_end_date(effective_date, contract_term_years, fallback_start_date=None):
    start_date = effective_date or fallback_start_date

    if start_date and contract_term_years:
        return add_years(start_date, contract_term_years) - timedelta(days=1)

    return None


def extract_area(text):
    cleaned = normalize_text(text)

    match = re.search(
        r"Total Area\s*[:\-]?\s*([\d,]+)\s*Sq",
        cleaned,
        re.I
    )

    if match:
        return clean_number(match.group(1))

    match = re.search(
        r"AED\s*[\d.]+\s*X\s*([\d,]+)",
        cleaned,
        re.I
    )

    if match:
        return clean_number(match.group(1))

    return 0


def get_land_lease_section(text):
    cleaned = normalize_text(text)

    match = re.search(
        r"Land\s+Lease\s*:?(.*?)(?:Throughput|Volume Commitments|Product Handling|$)",
        cleaned,
        re.I
    )

    if match:
        return match.group(1).strip()

    return cleaned


# --------------------------------------------------
# COMMERCIAL OPERATIONS DATE
# --------------------------------------------------

def extract_commercial_operations_date(text):
    cleaned = normalize_text(text)

    # Example: Commercial Operations date: 36 months from September 01, 2025
    match = re.search(
        rf"Commercial Operations date\s*[:\-]?\s*(\d+)\s*months?\s*from\s*({DATE_REGEX})",
        cleaned,
        re.I
    )

    if match:
        months = int(match.group(1))
        base_date = parse_date(match.group(2))

        if base_date:
            return base_date + relativedelta(months=months)

    # Example: Commercial Operations date: 42 months from Effective Date i.e. 25th October 2027
    match = re.search(
        rf"Commercial Operations date.*?i\.?e\.?\s*({DATE_REGEX})",
        cleaned,
        re.I
    )

    if match:
        return parse_date(match.group(1))

    return None


# --------------------------------------------------
# ESCALATION EXTRACTION
# --------------------------------------------------

def extract_date_based_escalation(section):
    section = normalize_text(section)

    match = re.search(
        rf"From\s*({DATE_REGEX})\s*to\s*({DATE_REGEX}).*?(\d+\.?\d*)\s*%",
        section,
        re.I
    )

    if match:
        return {
            "type": "date_based",
            "start_date": parse_date(match.group(1)),
            "end_date": parse_date(match.group(2)),
            "percent": float(match.group(3))
        }

    return None


def extract_cod_year_escalation(section):
    section = normalize_text(section)

    match = re.search(
        r"From\s*(\d+)(?:st|nd|rd|th)?\s*year\s+of\s+Commercial Operations\s*=\s*(\d+\.?\d*)\s*%",
        section,
        re.I
    )

    if match:
        return {
            "type": "cod_year_based",
            "from_year": int(match.group(1)),
            "percent": float(match.group(2))
        }

    return None


# --------------------------------------------------
# PATTERN 1: DATE-TO-DATE AED AMOUNT
# --------------------------------------------------

def extract_explicit_period_rows(section):
    rows = []

    section = normalize_text(section)
    area = extract_area(section)

    period_pattern = rf"(?:From\s*)?({DATE_REGEX})\s*to\s*({DATE_REGEX})"
    period_matches = list(re.finditer(period_pattern, section, re.I))

    for index, match in enumerate(period_matches):
        start_text = match.group(1)
        end_text = match.group(2)

        start_date = parse_date(start_text)
        end_date = parse_date(end_text)

        if not start_date or not end_date:
            continue

        segment_start = match.start()
        segment_end = (
            period_matches[index + 1].start()
            if index + 1 < len(period_matches)
            else len(section)
        )

        segment = section[segment_start:segment_end]

        # Skip escalation statement such as AED 2.5% escalation
        if re.search(r"AED\s*\d+\.?\d*\s*%", segment, re.I):
            continue

        # Area formula: AED 60 X 357,988
        rate_match = re.search(
            r"AED\s*([\d.]+)\s*X\s*([\d,]+)",
            segment,
            re.I
        )

        # Fixed amount: = AED 7,159,760
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
            amount_text = re.sub(r"\s+", "", amount_text)

            amount = clean_number(amount_text)

            charge_type = "Fixed Revenue"
            calculation_basis = "Fixed amount for specific period"

        rows.append({
            "Pattern": "Explicit Period",
            "Revenue Type": "Land Lease",
            "Start Date": start_date,
            "End Date": end_date,
            "Charge Type": charge_type,
            "Area Sqm": final_area,
            "Rate AED/Sqm/Annum": rate,
            "Amount AED": amount,
            "Amount AED Mn": to_mn(amount),
            "Escalation %": 0,
            "Calculation Basis": calculation_basis
        })

    return sorted(rows, key=lambda x: x["Start Date"])


def append_date_based_escalation(rows, section, contract_end_date):
    escalation = extract_date_based_escalation(section)

    if not escalation or not rows:
        return rows

    escalation_percent = escalation["percent"]
    escalation_start = escalation["start_date"] or rows[-1]["End Date"] + timedelta(days=1)

    if contract_end_date is None:
        contract_end_date = add_years(escalation_start, 30) - timedelta(days=1)

    last_row = rows[-1]

    base_rate = last_row["Rate AED/Sqm/Annum"]
    base_amount = last_row["Amount AED"]
    area = last_row["Area Sqm"]

    current_start = escalation_start
    year_no = 1

    while current_start <= contract_end_date:
        current_end = add_years(current_start, 1) - timedelta(days=1)

        if current_end > contract_end_date:
            current_end = contract_end_date

        if base_rate and base_rate > 0:
            escalated_rate = base_rate * ((1 + escalation_percent / 100) ** year_no)

            amount = period_amount_from_annual_rate(
                current_start,
                current_end,
                escalated_rate,
                area
            )

            calculation_basis = f"AED {round(escalated_rate, 2)} × {int(area)} sqm per annum"

        else:
            escalated_rate = 0
            amount = base_amount * ((1 + escalation_percent / 100) ** year_no)
            calculation_basis = f"Previous period revenue escalated by {escalation_percent}%"

        rows.append({
            "Pattern": "Explicit Period",
            "Revenue Type": "Land Lease",
            "Start Date": current_start,
            "End Date": current_end,
            "Charge Type": "Escalated Revenue",
            "Area Sqm": area,
            "Rate AED/Sqm/Annum": round(escalated_rate, 2),
            "Amount AED": amount,
            "Amount AED Mn": to_mn(amount),
            "Escalation %": escalation_percent,
            "Calculation Basis": calculation_basis
        })

        current_start = current_end + timedelta(days=1)
        year_no += 1

    return sorted(rows, key=lambda x: x["Start Date"])


# --------------------------------------------------
# PATTERN 2: HANDOVER + COD RATE SCHEDULE
# --------------------------------------------------

def extract_pre_cod_rate(section):
    section = normalize_text(section)

    match = re.search(
        r"Land Lease rate up to Commercial Operations date\s*[:\-]?\s*AED\s*([\d.]+)\s*/?\s*Sq\.?\s*M\s*/?\s*Annum",
        section,
        re.I
    )

    if match:
        return float(match.group(1))

    return None


def extract_cod_year_rates(section):
    section = normalize_text(section)

    pattern = (
        r"(\d+)(?:st|nd|rd|th)?\s*year\s+of\s+Commercial Operations"
        r"\s*=\s*AED\s*([\d.]+)\s*/?\s*Sq\.?\s*M\s*/?\s*Annum"
    )

    matches = re.findall(pattern, section, re.I)

    rates = []

    for year_no, rate in matches:
        rates.append({
            "year_no": int(year_no),
            "rate": float(rate)
        })

    return sorted(rates, key=lambda x: x["year_no"])


def build_rate_schedule_rows(full_text, section, contract_end_date):
    rows = []

    section = normalize_text(section)
    area = extract_area(section)

    effective_date = extract_effective_date(full_text)
    handover_date = extract_handover_date(full_text)
    cod_date = extract_commercial_operations_date(full_text)
    contract_term_years = extract_contract_term_years(full_text)

    billing_start = handover_date or effective_date

    if not contract_end_date:
        contract_end_date = calculate_contract_end_date(
            effective_date,
            contract_term_years,
            fallback_start_date=billing_start
        )

    if not area or not billing_start or not cod_date:
        return rows

    pre_cod_rate = extract_pre_cod_rate(section)

    # Pre-COD period: billing starts from handover date until COD - 1 day
    if pre_cod_rate:
        current_start = billing_start
        final_pre_cod_end = cod_date - timedelta(days=1)

        while current_start <= final_pre_cod_end:
            current_end = add_years(current_start, 1) - timedelta(days=1)

            if current_end > final_pre_cod_end:
                current_end = final_pre_cod_end

            amount = period_amount_from_annual_rate(
                current_start,
                current_end,
                pre_cod_rate,
                area
            )

            rows.append({
                "Pattern": "Handover-COD Rate Schedule",
                "Revenue Type": "Land Lease",
                "Start Date": current_start,
                "End Date": current_end,
                "Charge Type": "Pre-COD Rate Revenue",
                "Area Sqm": area,
                "Rate AED/Sqm/Annum": pre_cod_rate,
                "Amount AED": amount,
                "Amount AED Mn": to_mn(amount),
                "Escalation %": 0,
                "Calculation Basis": f"AED {pre_cod_rate} × {int(area)} sqm per annum"
            })

            current_start = current_end + timedelta(days=1)

    # COD year rates
    cod_rates = extract_cod_year_rates(section)

    for item in cod_rates:
        year_no = item["year_no"]
        rate = item["rate"]

        current_start = add_years(cod_date, year_no - 1)
        current_end = add_years(current_start, 1) - timedelta(days=1)

        if contract_end_date and current_start > contract_end_date:
            continue

        if contract_end_date and current_end > contract_end_date:
            current_end = contract_end_date

        amount = period_amount_from_annual_rate(
            current_start,
            current_end,
            rate,
            area
        )

        rows.append({
            "Pattern": "Handover-COD Rate Schedule",
            "Revenue Type": "Land Lease",
            "Start Date": current_start,
            "End Date": current_end,
            "Charge Type": f"COD Year {year_no} Rate Revenue",
            "Area Sqm": area,
            "Rate AED/Sqm/Annum": rate,
            "Amount AED": amount,
            "Amount AED Mn": to_mn(amount),
            "Escalation %": 0,
            "Calculation Basis": f"AED {rate} × {int(area)} sqm per annum"
        })

    # Escalation from COD year, example: From 5th year of Commercial Operations = 2.5%
    cod_escalation = extract_cod_year_escalation(section)

    if cod_escalation and cod_rates:
        escalation_percent = cod_escalation["percent"]
        from_year = cod_escalation["from_year"]

        last_known_rate = cod_rates[-1]["rate"]
        last_known_year = cod_rates[-1]["year_no"]

        if not contract_end_date:
            contract_end_date = add_years(cod_date, 30) - timedelta(days=1)

        current_year_no = from_year

        while True:
            current_start = add_years(cod_date, current_year_no - 1)

            if current_start > contract_end_date:
                break

            current_end = add_years(current_start, 1) - timedelta(days=1)

            if current_end > contract_end_date:
                current_end = contract_end_date

            escalation_power = current_year_no - last_known_year

            escalated_rate = last_known_rate * (
                (1 + escalation_percent / 100) ** escalation_power
            )

            amount = period_amount_from_annual_rate(
                current_start,
                current_end,
                escalated_rate,
                area
            )

            rows.append({
                "Pattern": "Handover-COD Rate Schedule",
                "Revenue Type": "Land Lease",
                "Start Date": current_start,
                "End Date": current_end,
                "Charge Type": f"COD Year {current_year_no} Escalated Revenue",
                "Area Sqm": area,
                "Rate AED/Sqm/Annum": round(escalated_rate, 2),
                "Amount AED": amount,
                "Amount AED Mn": to_mn(amount),
                "Escalation %": escalation_percent,
                "Calculation Basis": f"AED {round(escalated_rate, 2)} × {int(area)} sqm per annum"
            })

            current_year_no += 1

    return sorted(rows, key=lambda x: x["Start Date"])


# --------------------------------------------------
# MASTER LAND LEASE BUILDER
# --------------------------------------------------

def build_land_lease_terms(full_text):
    effective_date = extract_effective_date(full_text)
    handover_date = extract_handover_date(full_text)
    contract_term_years = extract_contract_term_years(full_text)

    contract_end_date = calculate_contract_end_date(
        effective_date,
        contract_term_years,
        fallback_start_date=handover_date
    )

    section = get_land_lease_section(full_text)

    explicit_rows = extract_explicit_period_rows(section)

    explicit_rows = append_date_based_escalation(
        explicit_rows,
        section,
        contract_end_date
    )

    rate_schedule_rows = build_rate_schedule_rows(
        full_text,
        section,
        contract_end_date
    )

    if rate_schedule_rows:
        return rate_schedule_rows, section, contract_end_date

    return explicit_rows, section, contract_end_date


# --------------------------------------------------
# PROJECTION ENGINE
# --------------------------------------------------

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


# --------------------------------------------------
# STREAMLIT APP
# --------------------------------------------------

if uploaded_file:
    raw_text = extract_file_text(uploaded_file)

    st.success("Contract text extracted successfully")

    with st.expander("View Extracted Contract Text"):
        st.text_area("Contract Content", raw_text, height=300)

    effective_date = extract_effective_date(raw_text)
    handover_date = extract_handover_date(raw_text)
    cod_date = extract_commercial_operations_date(raw_text)
    contract_term_years = extract_contract_term_years(raw_text)

    contract_end_date = calculate_contract_end_date(
        effective_date,
        contract_term_years,
        fallback_start_date=handover_date
    )

    header_df = pd.DataFrame([{
        "Effective Date": effective_date.date() if effective_date else "",
        "Handover Date": handover_date.date() if handover_date else "",
        "Commercial Operations Date": cod_date.date() if cod_date else "",
        "Contract Term Years": contract_term_years if contract_term_years else "",
        "Contract End Date": contract_end_date.date() if contract_end_date else ""
    }])

    st.subheader("Contract Header")
    st.dataframe(header_df, use_container_width=True)

    terms, land_section, detected_contract_end = build_land_lease_terms(raw_text)

    with st.expander("View Land Lease Section"):
        st.text_area("Land Lease Section", land_section, height=300)

    if not terms:
        st.error("No land lease terms extracted. Please check contract format.")
        st.stop()

    terms_df = pd.DataFrame(terms)

    st.subheader("Extracted Land Lease Terms")

    edited_terms_df = st.data_editor(
        terms_df,
        num_rows="dynamic",
        use_container_width=True,
        height=500
    )

    edited_terms_df["Start Date"] = pd.to_datetime(edited_terms_df["Start Date"])
    edited_terms_df["End Date"] = pd.to_datetime(edited_terms_df["End Date"])

    st.subheader("Projection Settings")

    min_year = int(edited_terms_df["Start Date"].dt.year.min())
    max_year = int(edited_terms_df["End Date"].dt.year.max())

    col1, col2 = st.columns(2)

    with col1:
        start_year = st.number_input("Start Calendar Year", value=min_year)

    with col2:
        end_year = st.number_input("End Calendar Year", value=max_year)

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

    st.dataframe(
        calendar_year_df,
        use_container_width=True,
        height=500
    )

    output = BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        header_df.to_excel(writer, index=False, sheet_name="Contract Header")
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
