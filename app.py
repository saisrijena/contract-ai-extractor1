import streamlit as st
import fitz
import pandas as pd
import re
from io import BytesIO
from datetime import datetime, timedelta

st.set_page_config(page_title="Contract Revenue Engine", layout="wide")
st.title("AI Contract Extraction & Revenue Projection Engine")

uploaded_file = st.file_uploader("Upload Contract PDF", type=["pdf"])

# ---------- HELPERS ----------

def extract_pdf_text(file):
    doc = fitz.open(stream=file.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text("text") + "\n"
    return text

def split_text_into_chunks(text, chunk_size=6000):
    chunks = []
    for i in range(0, len(text), chunk_size):
        chunks.append(text[i:i + chunk_size])
    return chunks

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
    value = str(value).replace(",", "").replace(" ", "")
    return float(value)

def to_mn(value):
    return round(float(value) / 1_000_000, 2)

def extract_area(text):
    cleaned = normalize_text(text)
    m = re.search(r"Total Area\s*[:\-]?\s*([\d,]+)\s*Sq", cleaned, re.I)
    return clean_number(m.group(1)) if m else 0

def extract_escalation(text):
    cleaned = normalize_text(text)
    m = re.search(r"(\d+\.?\d*)\s*%\s*escalation", cleaned, re.I)
    return float(m.group(1)) if m else 0

def overlap_days(a_start, a_end, b_start, b_end):
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    return max(0, (end - start).days + 1)

# ---------- LAND LEASE ----------

def extract_land_lease_terms(text):
    rows = []
    cleaned = normalize_text(text)

    area = extract_area(cleaned)
    escalation = extract_escalation(cleaned)

    land_section = cleaned
    if "Land Lease" in cleaned and "Throughput" in cleaned:
        land_section = cleaned.split("Land Lease", 1)[1].split("Throughput", 1)[0]

    date_regex = r"\d{1,2}\s*(?:st|nd|rd|th)?\s+\w+\s+\d{4}"
    pattern = rf"({date_regex})\s*to\s*({date_regex})\s*=\s*AED\s*([0-9][0-9,\s]*[0-9])"

    matches = re.finditer(pattern, land_section, re.I)

    for m in matches:
        start_txt = m.group(1)
        end_txt = m.group(2)
        amount_txt = m.group(3)

        amount_txt = re.split(r"\s+\d{1,2}\s*(?:st|nd|rd|th)?\s+\w+\s+\d{4}", amount_txt)[0]
        amount_txt = re.split(r"\s+From\s+", amount_txt, flags=re.I)[0]
        amount_txt = re.split(r"\s+And\s+", amount_txt, flags=re.I)[0]
        amount_txt = re.sub(r"\s+", "", amount_txt)

        start = parse_date(start_txt)
        end = parse_date(end_txt)

        if not start or not end:
            continue

        amount = clean_number(amount_txt)

        row_text = land_section[m.start():m.end()+100]
        rate_match = re.search(r"\(AED\s*([\d.]+)\s*[xX]\s*([\d,]+)", row_text, re.I)

        rate = 0
        charge_type = "Fixed Revenue"
        basis = "Fixed amount for specific period"

        if rate_match:
            rate = float(rate_match.group(1))
            charge_type = "Area Based"
            basis = f"AED {rate} × {int(area)} sqm"
            amount = rate * area

        rows.append({
            "Revenue Type": "Land Lease",
            "Start Date": start,
            "End Date": end,
            "Charge Type": charge_type,
            "Basis": basis,
            "Area Sqm": area,
            "Volume Tons": 0,
            "Rate": rate,
            "Amount AED": amount,
            "Amount AED Mn": to_mn(amount),
            "Escalation %": 0,
            "Remarks": "Extracted from land lease section"
        })

    if escalation > 0 and rows:
        last = rows[-1]
        esc_start = last["End Date"] + timedelta(days=1)
        esc_end = datetime(esc_start.year + 30, esc_start.month, esc_start.day)

        rows.append({
            "Revenue Type": "Land Lease",
            "Start Date": esc_start,
            "End Date": esc_end,
            "Charge Type": "Escalated Revenue",
            "Basis": f"Previous year amount escalated by {escalation}%",
            "Area Sqm": area,
            "Volume Tons": 0,
            "Rate": last["Rate"],
            "Amount AED": last["Amount AED"],
            "Amount AED Mn": to_mn(last["Amount AED"]),
            "Escalation %": escalation,
            "Remarks": "Escalation continues year on year"
        })

    return rows

# ---------- THROUGHPUT ----------

def extract_rate_slabs(text):
    cleaned = normalize_text(text)

    pattern = r"(Up to\s+[\d.]+\s*Million\s+tons?|[\d.]+\s+to\s+[\d.]+\s*Million\s+tons?)\s*[:=]\s*AED\s*([\d.]+)\s*per\s*Ton"
    matches = re.findall(pattern, cleaned, re.I)

    slabs = []

    for slab, rate in matches:
        nums = re.findall(r"[\d.]+", slab)

        if "up to" in slab.lower():
            min_tons = 0
            max_tons = float(nums[0]) * 1_000_000
        else:
            min_tons = float(nums[0]) * 1_000_000
            max_tons = float(nums[1]) * 1_000_000

        slabs.append({
            "Slab": slab,
            "Min Tons": min_tons,
            "Max Tons": max_tons,
            "Rate AED/Ton": float(rate)
        })

    return slabs

def get_rate_for_volume(volume, slabs):
    for slab in slabs:
        if volume > slab["Min Tons"] and volume <= slab["Max Tons"]:
            return slab["Rate AED/Ton"], slab["Slab"]

    if slabs:
        return slabs[-1]["Rate AED/Ton"], slabs[-1]["Slab"]

    return 0, "No rate found"

def extract_throughput_terms(text):
    rows = []
    cleaned = normalize_text(text)
    escalation = extract_escalation(cleaned)
    slabs = extract_rate_slabs(cleaned)

    date_regex = r"\d{1,2}\s*(?:st|nd|rd|th)?\s+\w+\s+\d{4}"
    pattern = rf"([\d.]+)\s*Million\s+tons?\s+from\s+({date_regex})\s*to\s*({date_regex})"

    matches = re.findall(pattern, cleaned, re.I)

    for volume_txt, start_txt, end_txt in matches:
        start = parse_date(start_txt)
        end = parse_date(end_txt)

        if not start or not end:
            continue

        volume = float(volume_txt) * 1_000_000
        rate, slab = get_rate_for_volume(volume, slabs)
        amount = volume * rate

        rows.append({
            "Revenue Type": "Throughput",
            "Start Date": start,
            "End Date": end,
            "Charge Type": "Volume Commitment",
            "Basis": slab,
            "Area Sqm": 0,
            "Volume Tons": volume,
            "Rate": rate,
            "Amount AED": amount,
            "Amount AED Mn": to_mn(amount),
            "Escalation %": escalation,
            "Remarks": "Volume commitment × handling rate"
        })

    if rows:
        last = rows[-1]
        steady_start = last["End Date"] + timedelta(days=1)
        steady_end = datetime(steady_start.year + 30, steady_start.month, steady_start.day)

        rows.append({
            "Revenue Type": "Throughput",
            "Start Date": steady_start,
            "End Date": steady_end,
            "Charge Type": "Steady State",
            "Basis": last["Basis"],
            "Area Sqm": 0,
            "Volume Tons": last["Volume Tons"],
            "Rate": last["Rate"],
            "Amount AED": last["Amount AED"],
            "Amount AED Mn": to_mn(last["Amount AED"]),
            "Escalation %": escalation,
            "Remarks": "Steady state volume continues"
        })

    return rows, slabs

# ---------- PROJECTION ----------

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

def escalated_amount(term, q_start):
    amount = term["Amount AED"]

    if term["Escalation %"] > 0:
        years_passed = max(0, q_start.year - term["Start Date"].year)
        amount = amount * ((1 + term["Escalation %"] / 100) ** years_passed)

    return amount

def build_quarterly_projection(terms, start_year, end_year):
    output = []

    for quarter, q_start, q_end in quarter_ranges(start_year, end_year):
        land = 0
        throughput = 0
        logic = []

        for term in terms:
            days = overlap_days(term["Start Date"], term["End Date"], q_start, q_end)

            if days <= 0:
                continue

            total_days = (term["End Date"] - term["Start Date"]).days + 1
            full_value = escalated_amount(term, q_start)
            q_value = full_value * days / total_days

            if term["Revenue Type"] == "Land Lease":
                land += q_value
            elif term["Revenue Type"] == "Throughput":
                throughput += q_value

            logic.append(
                f"{term['Revenue Type']} - {term['Charge Type']}: AED {to_mn(q_value)} Mn = "
                f"AED {to_mn(full_value)} Mn × {days}/{total_days}"
            )

        output.append({
            "Quarter": quarter,
            "Quarter Start": q_start.date(),
            "Quarter End": q_end.date(),
            "Land Lease AED Mn": to_mn(land),
            "Throughput AED Mn": to_mn(throughput),
            "Total AED Mn": to_mn(land + throughput),
            "Calculation Logic": " | ".join(logic)
        })

    return pd.DataFrame(output)

# ---------- APP ----------

if uploaded_file:
    raw_text = extract_pdf_text(uploaded_file)

    chunks = split_text_into_chunks(raw_text)

    st.success("PDF Text Extracted Successfully")
    st.write(f"Contract split into {len(chunks)} chunks for AI reading.")

    with st.expander("View Extracted Contract Text"):
        st.text_area("Contract Content", raw_text, height=300)

    with st.expander("View Text Chunks"):
        for i, chunk in enumerate(chunks, start=1):
            st.text_area(f"Chunk {i}", chunk, height=150)

    land_terms = extract_land_lease_terms(raw_text)
    throughput_terms, slabs = extract_throughput_terms(raw_text)

    terms = land_terms + throughput_terms

    if not terms:
        st.error("No commercial terms extracted. Please check PDF format.")
        st.stop()

    terms_df = pd.DataFrame(terms)

    st.subheader("Extracted Commercial Terms")
    edited_terms_df = st.data_editor(terms_df, num_rows="dynamic")

    st.subheader("Throughput Rate Slabs")
    slabs_df = pd.DataFrame(slabs)
    st.dataframe(slabs_df)

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

    st.subheader("Quarterly Revenue Projection")
    st.dataframe(projection_df)

    yearly_df = projection_df.copy()
    yearly_df["Calendar Year"] = yearly_df["Quarter"].str[-4:]

    calendar_year_df = yearly_df.groupby("Calendar Year")[[
        "Land Lease AED Mn",
        "Throughput AED Mn",
        "Total AED Mn"
    ]].sum().reset_index()

    calendar_year_df[[
        "Land Lease AED Mn",
        "Throughput AED Mn",
        "Total AED Mn"
    ]] = calendar_year_df[[
        "Land Lease AED Mn",
        "Throughput AED Mn",
        "Total AED Mn"
    ]].round(2)

    st.subheader("Calendar Year Revenue Projection")
    st.dataframe(calendar_year_df)

    output = BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        edited_terms_df.to_excel(writer, index=False, sheet_name="Extracted Terms")
        slabs_df.to_excel(writer, index=False, sheet_name="Rate Slabs")
        projection_df.to_excel(writer, index=False, sheet_name="Quarterly Projection")
        calendar_year_df.to_excel(writer, index=False, sheet_name="Calendar Year Revenue")

    output.seek(0)

    st.download_button(
        "Download Full Revenue Projection Excel",
        data=output,
        file_name="contract_revenue_projection.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
