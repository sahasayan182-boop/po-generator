import streamlit as st
import pandas as pd
import io
import re
from rapidfuzz import fuzz

# =====================================================
# PAGE CONFIG
# =====================================================

st.set_page_config(
    page_title="Purchase Order System",
    layout="wide"
)

# =====================================================
# MODERN CSS (SOFT SHADOW CARDS)
# =====================================================

st.markdown("""
<style>

.main-header {
    font-size:28px;
    font-weight:600;
    margin-bottom:10px;
}

.card {
    background-color:#ffffff;
    padding:20px;
    border-radius:12px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.08);
    margin-bottom:20px;
}

.card-title {
    font-size:18px;
    font-weight:600;
    margin-bottom:15px;
}

.stock-green {color:#16a34a;font-weight:600;}
.stock-orange {color:#ea580c;font-weight:600;}
.stock-red {color:#dc2626;font-weight:600;}

.totals-card {
    background-color:#ffffff;
    padding:20px;
    border-radius:12px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.08);
}

.workflow {
    font-size:14px;
    margin-bottom:15px;
    color:#555;
}

</style>
""", unsafe_allow_html=True)

# =====================================================
# HEADER
# =====================================================

st.markdown('<div class="main-header">Purchase Order System</div>', unsafe_allow_html=True)
st.divider()

# =====================================================
# SESSION STATE
# =====================================================

if "pattern_confirmed" not in st.session_state:
    st.session_state.pattern_confirmed = False

if "po_items" not in st.session_state:
    st.session_state.po_items = []

if "final_df" not in st.session_state:
    st.session_state.final_df = None

# =====================================================
# FILE UPLOAD CARD
# =====================================================

with st.container():

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="card-title">Data Source</div>', unsafe_allow_html=True)

    col1, col2 = st.columns(2)

    sales_file = col1.file_uploader("Sales Register", type=["xlsx"])
    stock_file = col2.file_uploader("Stock Report", type=["xlsx"])

    st.markdown('</div>', unsafe_allow_html=True)

if not sales_file or not stock_file:
    st.stop()

# =====================================================
# LOAD DATA
# =====================================================

@st.cache_data
def load_sales(file):

    df = pd.read_excel(file, sheet_name="data")

    df.columns = df.columns.str.strip()

    df["Invoice Date"] = pd.to_datetime(df["Invoice Date"])

    df["ITEM CODE"] = df["Item Code"].astype(str).str.upper()
    df["PRODUCT"] = df["Product"].fillna("").astype(str).str.upper()
    df["OEM"] = df["Oem"].fillna("").astype(str).str.upper()
    df["CUSTOMER"] = df["Customer Name"].fillna("").astype(str).str.upper()

    df["RATE"] = df["Rate"].astype(float)

    df["SEARCH"] = df["ITEM CODE"] + " " + df["PRODUCT"] + " " + df["OEM"]

    df = df.sort_values("Invoice Date", ascending=False)

    unique_products = df.drop_duplicates("ITEM CODE")

    customers = sorted(df["CUSTOMER"].unique())

    return df, unique_products, customers

sales_df, unique_products, customer_list = load_sales(sales_file)

@st.cache_data
def load_stock(file):

    df = pd.read_excel(file)

    df.columns = df.columns.str.strip()

    df["ITEM CODE"] = df["Item code"].astype(str).str.upper()
    df["STOCK"] = df["Total Qty"].astype(float)
    df["WH CODE"] = df["WH Code"].astype(str)

    return df

stock_df = load_stock(stock_file)

stock_lookup = stock_df.groupby("ITEM CODE")["STOCK"].sum().to_dict()
wh_lookup = stock_df.groupby("ITEM CODE")["WH CODE"].apply(list).to_dict()

# =====================================================
# CUSTOMER & SETTINGS CARD
# =====================================================

with st.container():

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="card-title">Customer & Settings</div>', unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)

    selected_customer = col1.selectbox("Customer", [""] + customer_list)

    discount_option = col2.selectbox("Discount", ["3%", "2.5%", "0%"])
    gst_option = col3.selectbox("GST", ["0%", "5%", "12%", "18%", "28%"], index=3)

    discount_rate = float(discount_option.replace("%",""))/100
    gst_rate = float(gst_option.replace("%",""))/100

    st.markdown('</div>', unsafe_allow_html=True)

# =====================================================
# ORDER INPUT CARD
# =====================================================

with st.container():

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="card-title">Enter Order</div>', unsafe_allow_html=True)

    order_text = st.text_area("", height=150)

    generate_clicked = st.button("Generate Purchase Order")

    st.markdown('</div>', unsafe_allow_html=True)

# =====================================================
# HELPER FUNCTIONS
# =====================================================

def detect_numbers(line):
    return re.findall(r'\b\d+\b', line)

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

def get_price(item_code, override_price):

    if override_price:
        return override_price

    if selected_customer:

        cust_rows = sales_df[
            (sales_df["ITEM CODE"] == item_code) &
            (sales_df["CUSTOMER"] == selected_customer)
        ]

        if not cust_rows.empty:
            return cust_rows.iloc[0]["RATE"]

    rows = sales_df[sales_df["ITEM CODE"] == item_code]

    if not rows.empty:
        return rows.iloc[0]["RATE"]

    return 0

# =====================================================
# GENERATE PO ITEMS
# =====================================================

if generate_clicked:

    st.session_state.po_items = []

    lines = [l for l in order_text.split("\n") if l.strip()]

    for line in lines:

        nums = detect_numbers(line)

        qty = int(nums[0]) if nums else 1
        price_override = float(nums[-1]) if len(nums) >= 2 else None

        product = line

        for n in nums:
            product = product.replace(n, "")

        candidates = find_candidates(product)

        st.session_state.po_items.append({

            "raw_line": line,
            "qty": qty,
            "price": price_override,
            "candidates": candidates

        })

# =====================================================
# CONFIRM PRODUCTS CARD
# =====================================================

if st.session_state.po_items:

    with st.container():

        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="card-title">Confirm Products</div>', unsafe_allow_html=True)

        final_rows = []

        for i, item in enumerate(st.session_state.po_items):

            st.markdown(f"**Original:** `{item['raw_line']}`")

            options = [
                f"{c['ITEM CODE']} | {c['PRODUCT']}"
                for c in item["candidates"]
            ]

            selected = st.selectbox("Product", options, key=f"prod{i}")

            code = selected.split("|")[0]

            wh_list = wh_lookup.get(code, [])

            wh = st.selectbox("Warehouse", wh_list, key=f"wh{i}")

            stock = stock_lookup.get(code, 0)

            if stock == 0:
                st.markdown(f'<span class="stock-red">Stock: {stock}</span>', unsafe_allow_html=True)
            elif stock <= 5:
                st.markdown(f'<span class="stock-orange">Stock: {stock}</span>', unsafe_allow_html=True)
            else:
                st.markdown(f'<span class="stock-green">Stock: {stock}</span>', unsafe_allow_html=True)

            price = get_price(code, item["price"])

            final_rows.append({

                "ITEM CODE": code,
                "PRODUCT": selected,
                "WH CODE": wh,
                "STOCK": stock,
                "QUANTITY": item["qty"],
                "PRICE": price

            })

        confirm = st.button("Confirm Selection")

        st.markdown('</div>', unsafe_allow_html=True)

        if confirm:

            df = pd.DataFrame(final_rows)

            df["AMOUNT"] = df["QUANTITY"] * df["PRICE"]

            st.session_state.final_df = df

# =====================================================
# PO TABLE + TOTALS CARD
# =====================================================

if st.session_state.final_df is not None:

    col1, col2 = st.columns([4,1])

    with col1:

        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="card-title">Purchase Order</div>', unsafe_allow_html=True)

        edited_df = st.data_editor(st.session_state.final_df, use_container_width=True)

        edited_df["AMOUNT"] = edited_df["QUANTITY"] * edited_df["PRICE"]

        st.session_state.final_df = edited_df

        st.markdown('</div>', unsafe_allow_html=True)

    subtotal = edited_df["AMOUNT"].sum()
    discount = subtotal * discount_rate
    gst = (subtotal - discount) * gst_rate
    total = subtotal - discount + gst

    with col2:

        st.markdown('<div class="totals-card">', unsafe_allow_html=True)

        st.markdown(f"""
        Subtotal: ₹{subtotal:,.2f}<br>
        Discount ({discount_option}): ₹{discount:,.2f}<br>
        GST ({gst_option}): ₹{gst:,.2f}<br>
        <hr>
        <b>Total: ₹{total:,.2f}</b>
        """, unsafe_allow_html=True)

        st.markdown('</div>', unsafe_allow_html=True)

    buffer = io.BytesIO()

    export_df = edited_df.copy()

    totals = pd.DataFrame({
        "PRICE": ["Subtotal", f"Discount ({discount_option})", f"GST ({gst_option})", "TOTAL"],
        "AMOUNT": [subtotal, discount, gst, total]
    })

    final_export = pd.concat([export_df, totals])

    final_export.to_excel(buffer, index=False)

    st.download_button("Download Excel", buffer.getvalue(), "PO.xlsx")
