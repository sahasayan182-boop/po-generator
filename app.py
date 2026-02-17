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
.stApp {
    background-color: #f5f7fb;
}
.totals-card {
    background: white;
    padding: 18px;
    border-radius: 10px;
    border: 1px solid #e5e7eb;
    width: 100%;
    min-width: 260px;
    max-width: 380px;
}
.total-line {
    display: flex;
    justify-content: space-between;
    margin-bottom: 6px;
}
.total-final {
    font-size: 20px;
    font-weight: 700;
}
.number-box {
    background:#ffffff;
    padding:10px;
    border-radius:8px;
    border:1px solid #e5e7eb;
    margin-bottom:8px;
}
</style>
""", unsafe_allow_html=True)

st.title("Purchase Order System")

PRIMARY_WH = ["BWD_MAIN","FBD_MAIN","CHN_CENTRL","KOL_MAIN"]

# =====================================================
# SESSION STATE INIT
# =====================================================

if "po_items" not in st.session_state:
    st.session_state.po_items = []

if "final_df" not in st.session_state:
    st.session_state.final_df = None

if "confirmation_data" not in st.session_state:
    st.session_state.confirmation_data = None

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
# LOAD DATA
# =====================================================

@st.cache_data
def load_sales(file):

    df = pd.read_excel(file, sheet_name="data")

    df.columns = df.columns.str.strip()

    df["ITEM CODE"] = df["Item Code"].astype(str).str.upper()
    df["PRODUCT"] = df["Product"].fillna("").astype(str).str.upper()
    df["CUSTOMER"] = df["Customer Name"].fillna("").astype(str).str.upper()
    df["RATE"] = df["Rate"].astype(float)

    df["SEARCH"] = df["ITEM CODE"] + " " + df["PRODUCT"]

    df = df.sort_values("Invoice Date", ascending=False)

    unique = df.drop_duplicates("ITEM CODE")

    customers = sorted(df["CUSTOMER"].unique())

    return df, unique, customers

sales_df, unique_products, customers = load_sales(sales_file)

@st.cache_data
def load_stock(file):

    df = pd.read_excel(file)

    df.columns = df.columns.str.strip().str.upper()

    df["ITEM CODE"] = df["ITEM CODE"].astype(str).str.upper()
    df["TOTAL QTY"] = df["TOTAL QTY"].astype(float)
    df["WH CODE"] = df["WH CODE"].astype(str).str.upper()

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

unit_pattern = re.compile(r'\d+\.?\d*(m|cm|mm|gb|tb|ghz|hz|inch|")', re.IGNORECASE)

def extract_numbers_with_context(line):

    parts = re.findall(r'\d+\.?\d*[a-zA-Z"]*', line)

    return parts

def is_unit_number(part):

    return bool(unit_pattern.match(part))

def find_candidates(query):

    query = query.upper()

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

        cust_rows = sales_df[
            (sales_df["ITEM CODE"] == code) &
            (sales_df["CUSTOMER"] == selected_customer)
        ]

        if not cust_rows.empty:
            return cust_rows.iloc[0]["RATE"]

    rows = sales_df[sales_df["ITEM CODE"] == code]

    if not rows.empty:
        return rows.iloc[0]["RATE"]

    return 0

# =====================================================
# NUMBER CONFIRMATION STEP
# =====================================================

if generate:

    lines = [l.strip() for l in order_text.split("\n") if l.strip()]

    confirmation_data = []

    for line in lines:

        parts = extract_numbers_with_context(line)

        confirmation_data.append({
            "line": line,
            "parts": parts
        })

    st.session_state.confirmation_data = confirmation_data

# =====================================================
# SHOW CONFIRMATION UI
# =====================================================

if st.session_state.confirmation_data:

    st.subheader("Confirm Numbers")

    qty_price_map = {}

    for idx, entry in enumerate(st.session_state.confirmation_data):

        line = entry["line"]
        parts = entry["parts"]

        st.markdown(f"**{line}**")

        for part in parts:

            default = "Ignore"

            if is_unit_number(part):
                default = "Ignore"
            else:
                num = float(re.findall(r'\d+\.?\d*', part)[0])
                if num >= 10:
                    default = "Price"
                else:
                    default = "Quantity"

            choice = st.radio(
                f"{part}",
                ["Quantity","Price","Ignore"],
                index=["Quantity","Price","Ignore"].index(default),
                key=f"{idx}_{part}"
            )

            qty_price_map[(line, part)] = choice

    if st.button("Confirm and Generate PO"):

        po_items = []

        for entry in st.session_state.confirmation_data:

            line = entry["line"]
            parts = entry["parts"]

            qty = None
            price_override = None

            for part in parts:

                choice = qty_price_map[(line, part)]

                num = float(re.findall(r'\d+\.?\d*', part)[0])

                if choice == "Quantity":
                    qty = int(num)

                elif choice == "Price":
                    price_override = num

            if qty is None:
                qty = 1

            product = line

            for part in parts:
                product = product.replace(part,"")

            candidates = find_candidates(product)

            po_items.append({
                "raw": line,
                "qty": qty,
                "price": price_override,
                "candidates": candidates
            })

        st.session_state.po_items = po_items
        st.session_state.confirmation_data = None

# =====================================================
# PRODUCT CONFIRMATION
# =====================================================

if st.session_state.po_items:

    st.subheader("Confirm Products")

    rows = []

    for i,item in enumerate(st.session_state.po_items):

        st.markdown(f"**{item['raw']}**")

        options = [f"{c['ITEM CODE']} | {c['PRODUCT']}" for c in item["candidates"]]

        selected = st.selectbox("Product", options, key=f"prod{i}")

        code = selected.split("|")[0]

        wh_list = wh_lookup.get(code, [])

        primary = [w for w in PRIMARY_WH if w in wh_list]
        secondary = [w for w in wh_list if w not in PRIMARY_WH]

        wh_sorted = primary + sorted(secondary)

        wh = st.selectbox("Warehouse", wh_sorted, key=f"wh{i}")

        stock = stock_lookup.get(code,0)

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
# TABLE + TOTALS
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

    st.download_button("Download PO Excel", buffer.getvalue(), "Purchase_Order.xlsx")
