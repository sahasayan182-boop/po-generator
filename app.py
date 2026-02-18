import streamlit as st
import pandas as pd
import io
import re
from rapidfuzz import fuzz

st.set_page_config(page_title="Purchase Order System", layout="wide")

# =====================================================
# CSS
# =====================================================

st.markdown("""
<style>
.stApp {background-color:#f5f7fb;}

.totals-card {
    background:white;
    padding:18px;
    border-radius:10px;
    border:1px solid #e5e7eb;
    width:100%;
    min-width:260px;
    max-width:380px;
}

.total-line {
    display:flex;
    justify-content:space-between;
    margin-bottom:6px;
}

.total-final {
    font-size:20px;
    font-weight:700;
}
</style>
""", unsafe_allow_html=True)

st.title("Purchase Order System")

PRIMARY_WH = ["BWD_MAIN","FBD_MAIN","CHN_CENTRL","KOL_MAIN"]

# =====================================================
# SESSION STATE
# =====================================================

if "po_items" not in st.session_state:
    st.session_state.po_items = []

if "final_df" not in st.session_state:
    st.session_state.final_df = None

if "ambiguous_lines" not in st.session_state:
    st.session_state.ambiguous_lines = None

# =====================================================
# DATA SOURCE
# =====================================================

st.subheader("Data Source")

col1, col2 = st.columns(2)

sales_file = col1.file_uploader("Sales Register", type=["xlsx"])
stock_file = col2.file_uploader("Stock Report", type=["xlsx"])

if not sales_file or not stock_file:
    st.stop()

# =====================================================
# LOAD SALES
# =====================================================

@st.cache_data
def load_sales(file):

    df = pd.read_excel(file, sheet_name="data")

    df.columns = df.columns.str.strip()

    df["ITEM CODE"] = df["Item Code"].astype(str).str.strip().str.upper()
    df["PRODUCT"] = df["Product"].fillna("").astype(str).str.strip().str.upper()
    df["OEM"] = df["Oem"].fillna("").astype(str).str.strip().str.upper()
    df["CUSTOMER"] = df["Customer Name"].fillna("").astype(str).str.strip().str.upper()
    df["RATE"] = df["Rate"].astype(float)

    df["SEARCH"] = (
        df["ITEM CODE"] + " " +
        df["PRODUCT"] + " " +
        df["OEM"]
    )

    df = df.sort_values("Invoice Date", ascending=False)

    unique_products = df.drop_duplicates("ITEM CODE")

    customers = sorted(df["CUSTOMER"].unique())

    return df, unique_products, customers

sales_df, unique_products, customers = load_sales(sales_file)

# =====================================================
# LOAD STOCK
# =====================================================

@st.cache_data
def load_stock(file):

    df = pd.read_excel(file)

    df.columns = df.columns.str.strip().str.upper()

    df["ITEM CODE"] = df["ITEM CODE"].astype(str).str.strip().str.upper()
    df["WH CODE"] = df["WH CODE"].astype(str).str.strip().str.upper()
    df["TOTAL QTY"] = df["TOTAL QTY"].astype(float)

    return df

stock_df = load_stock(stock_file)

stock_lookup = stock_df.groupby("ITEM CODE")["TOTAL QTY"].sum().to_dict()
wh_lookup = stock_df.groupby("ITEM CODE")["WH CODE"].apply(list).to_dict()

# =====================================================
# CUSTOMER SETTINGS
# =====================================================

st.subheader("Customer & Settings")

col1, col2, col3 = st.columns(3)

selected_customer = col1.selectbox("Customer", [""] + customers)
discount_option = col2.selectbox("Discount", ["3%","2.5%","0%"])
gst_option = col3.selectbox("GST", ["0%","5%","12%","18%","28%"], index=3)

discount_rate = float(discount_option.replace("%","")) / 100
gst_rate = float(gst_option.replace("%","")) / 100

# =====================================================
# ORDER INPUT
# =====================================================

st.subheader("Enter Order")

order_text = st.text_area("", height=150)

generate = st.button("Generate Purchase Order")

# =====================================================
# HELPERS
# =====================================================

pure_int_pattern = re.compile(r'^\d+$')

unit_pattern = re.compile(r'\d+[a-zA-Z"]')

def extract_parts(line):

    parts = re.findall(r'\S+', line)

    pure_ints = []
    ignored = []

    for p in parts:

        if pure_int_pattern.match(p):
            pure_ints.append(p)

        elif unit_pattern.search(p):
            ignored.append(p)

    return pure_ints

def find_candidates(query):

    query = query.upper().strip()

    results = []

    for _, row in unique_products.iterrows():

        score = fuzz.partial_ratio(query, row["SEARCH"])

        if score > 60:

            results.append({
                "ITEM CODE": row["ITEM CODE"],
                "PRODUCT": row["PRODUCT"]
            })

    return results[:20]

def get_price(code, override):

    if override is not None:
        return override

    if selected_customer:

        cust = sales_df[
            (sales_df["ITEM CODE"] == code) &
            (sales_df["CUSTOMER"] == selected_customer)
        ]

        if not cust.empty:
            return cust.iloc[0]["RATE"]

    rows = sales_df[sales_df["ITEM CODE"] == code]

    if not rows.empty:
        return rows.iloc[0]["RATE"]

    return 0

# =====================================================
# GENERATE LOGIC
# =====================================================

if generate:

    lines = [l.strip() for l in order_text.split("\n") if l.strip()]

    po_items = []

    ambiguous = []

    for line in lines:

        ints = extract_parts(line)

        if len(ints) == 0:

            st.warning(f"No quantity detected: {line}")
            continue

        if len(ints) > 2:

            ambiguous.append(line)
            continue

        qty = int(ints[0])

        price_override = None

        if len(ints) == 2:
            price_override = float(ints[1])

        product = line

        for i in ints:
            product = product.replace(i,"")

        candidates = find_candidates(product)

        po_items.append({
            "raw": line,
            "qty": qty,
            "price": price_override,
            "candidates": candidates
        })

    if ambiguous:
        st.session_state.ambiguous_lines = ambiguous
    else:
        st.session_state.po_items = po_items

# =====================================================
# CONFIRM PRODUCTS
# =====================================================

if st.session_state.po_items:

    st.subheader("Confirm Products")

    rows = []

    for i,item in enumerate(st.session_state.po_items):

        st.markdown(f"**{item['raw']}**")

        options = [
            f"{c['ITEM CODE']} | {c['PRODUCT']}"
            for c in item["candidates"]
        ]

        if not options:
            st.warning("No product match found")
            continue

        selected = st.selectbox("Product", options, key=f"prod{i}")

        code = selected.split("|")[0].strip().upper()

        wh_list = wh_lookup.get(code, [])

        primary = [w for w in PRIMARY_WH if w in wh_list]
        secondary = [w for w in wh_list if w not in PRIMARY_WH]

        wh_sorted = primary + sorted(secondary)

        if not wh_sorted:
            st.warning("No warehouse stock found")
            continue

        wh = st.selectbox("Warehouse", wh_sorted, key=f"wh{i}")

        stock = stock_lookup.get(code, 0)

        st.write(f"Stock Available: {stock}")

        price = get_price(code, item["price"])

        rows.append({
            "ITEM CODE": code,
            "PRODUCT": selected,
            "WH CODE": wh,
            "STOCK": stock,
            "QUANTITY": item["qty"],
            "PRICE": price,
            "AMOUNT": price * item["qty"]
        })

    if st.button("Confirm Selection"):

        st.session_state.final_df = pd.DataFrame(rows)

# =====================================================
# TABLE
# =====================================================

if st.session_state.final_df is not None:

    st.subheader("Purchase Order")

    edited_df = st.data_editor(
        st.session_state.final_df,
        use_container_width=True,
        key="po_table"
    )

    if st.button("Refresh Table"):

        edited_df["AMOUNT"] = edited_df["QUANTITY"] * edited_df["PRICE"]

        st.session_state.final_df = edited_df

        st.rerun()

    edited_df["AMOUNT"] = edited_df["QUANTITY"] * edited_df["PRICE"]

    st.session_state.final_df = edited_df

    subtotal = edited_df["AMOUNT"].sum()
    discount = subtotal * discount_rate
    gst = (subtotal - discount) * gst_rate
    total = subtotal - discount + gst

    col_space, col_totals = st.columns([3,1])

    with col_totals:

        st.markdown(f"""
        <div class="totals-card">
        <div class="total-line"><span>Subtotal</span><span>₹{subtotal:,.2f}</span></div>
        <div class="total-line"><span>Discount ({discount_option})</span><span>₹{discount:,.2f}</span></div>
        <div class="total-line"><span>GST ({gst_option})</span><span>₹{gst:,.2f}</span></div>
        <hr>
        <div class="total-line total-final"><span>Total</span><span>₹{total:,.2f}</span></div>
        </div>
        """, unsafe_allow_html=True)

    buffer = io.BytesIO()

    export_df = edited_df.copy()

    totals_df = pd.DataFrame({
        "PRICE":["Subtotal",f"Discount ({discount_option})",f"GST ({gst_option})","TOTAL"],
        "AMOUNT":[subtotal,discount,gst,total]
    })

    final_export = pd.concat([export_df, totals_df])

    final_export.to_excel(buffer, index=False)

    st.download_button(
        "Download PO Excel",
        buffer.getvalue(),
        "Purchase_Order.xlsx"
    )
