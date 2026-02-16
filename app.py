import streamlit as st
import pandas as pd
import io
import re
from rapidfuzz import fuzz

# =====================================================
# PAGE CONFIG
# =====================================================

st.set_page_config(page_title="Purchase Order Generator", layout="wide")
st.title("Purchase Order Generator")

PRIMARY_WAREHOUSES = [
    "BWD_MAIN",
    "FBD_MAIN",
    "CHN_CENTRL",
    "KOL_MAIN"
]

# =====================================================
# SESSION STATE INIT
# =====================================================

if "po_items" not in st.session_state:
    st.session_state.po_items = []

if "final_df" not in st.session_state:
    st.session_state.final_df = None

# =====================================================
# FILE UPLOAD
# =====================================================

col1, col2 = st.columns(2)

sales_file = col1.file_uploader("Upload Sales Register", type=["xlsx"])
stock_file = col2.file_uploader("Upload Stock Report", type=["xlsx"])

if not sales_file or not stock_file:
    st.stop()

# =====================================================
# LOAD SALES DATA
# =====================================================

@st.cache_data
def load_sales(file):

    df = pd.read_excel(file, sheet_name="data")

    df.columns = df.columns.str.strip()

    df["Invoice Date"] = pd.to_datetime(df["Invoice Date"])

    df["ITEM CODE"] = df["Item Code"].astype(str).str.upper()
    df["OEM"] = df["Oem"].fillna("").astype(str).str.upper()
    df["PRODUCT"] = df["Product"].fillna("").astype(str).str.upper()
    df["CUSTOMER"] = df["Customer Name"].fillna("").astype(str).str.upper()

    df["RATE"] = df["Rate"].astype(float)

    df["SEARCH_TEXT"] = (
        df["ITEM CODE"] + " " +
        df["OEM"] + " " +
        df["PRODUCT"]
    )

    df = df.sort_values("Invoice Date", ascending=False)

    unique_products = df.drop_duplicates("ITEM CODE")

    customers = sorted(df["CUSTOMER"].unique())

    return df, unique_products, customers

sales_df, unique_products, customer_list = load_sales(sales_file)

# =====================================================
# CUSTOMER SELECTOR (SEARCHABLE DROPDOWN)
# =====================================================

selected_customer = st.selectbox(
    "Select Customer",
    options=[""] + customer_list,
    index=0
)

# =====================================================
# LOAD STOCK DATA
# =====================================================

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
# GST + DISCOUNT
# =====================================================

col3, col4 = st.columns(2)

discount_option = col3.selectbox("Discount", ["3%", "2.5%", "0%"], index=0)
discount_rate = float(discount_option.replace("%",""))/100

gst_option = col4.selectbox("GST", ["0%", "5%", "12%", "18%", "28%"], index=3)
gst_rate = float(gst_option.replace("%",""))/100

# =====================================================
# SAFE PARSER
# =====================================================

def extract_price(line):

    price_patterns = [
        r'@(\d+)',
        r'₹\s*(\d+)',
        r'rs\.?\s*(\d+)',
        r'(\d+)\+'
    ]

    for pattern in price_patterns:
        match = re.search(pattern, line.lower())
        if match:
            return float(match.group(1))

    return None


def extract_quantity(line, price):

    numbers = re.findall(r'\b\d+\b', line)

    nums = [int(n) for n in numbers]

    if price and int(price) in nums:
        nums.remove(int(price))

    if nums:
        return nums[-1]

    return 1


def extract_product(line, qty, price):

    text = line

    if price:
        text = re.sub(r'@?\s*₹?\s*rs?\s*\.?\s*' + str(int(price)), '', text, flags=re.IGNORECASE)

    text = re.sub(r'\b' + str(qty) + r'\b', '', text)

    return text.strip()

# =====================================================
# SEARCH ENGINE
# =====================================================

def find_candidates(query):

    query = query.upper()

    results = []

    for _, row in unique_products.iterrows():

        score = fuzz.partial_ratio(query, row["SEARCH_TEXT"])

        if score > 60:
            results.append({
                "ITEM CODE": row["ITEM CODE"],
                "PRODUCT": row["PRODUCT"],
                "OEM": row["OEM"]
            })

    return results[:30]

# =====================================================
# PRICING ENGINE
# =====================================================

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

    global_rows = sales_df[sales_df["ITEM CODE"] == item_code]

    if not global_rows.empty:
        return global_rows.iloc[0]["RATE"]

    return 0

# =====================================================
# ORDER INPUT
# =====================================================

order_text = st.text_area("Enter Order")

if st.button("Generate Purchase Order"):

    st.session_state.po_items = []

    for line in order_text.split("\n"):

        if not line.strip():
            continue

        price = extract_price(line)
        qty = extract_quantity(line, price)
        product = extract_product(line, qty, price)

        candidates = find_candidates(product)

        st.session_state.po_items.append({
            "query": product,
            "qty": qty,
            "price": price,
            "candidates": candidates
        })

# =====================================================
# CONFIRM PRODUCTS
# =====================================================

if st.session_state.po_items:

    final_rows = []

    for idx, item in enumerate(st.session_state.po_items):

        st.subheader(f"Confirm Product: {item['query']}")

        options = [
            f"{c['ITEM CODE']} | {c['PRODUCT']}"
            for c in item["candidates"]
        ]

        selected = st.selectbox("Product", options, key=f"prod_{idx}")

        selected_code = selected.split("|")[0].strip()

        row = sales_df[sales_df["ITEM CODE"] == selected_code].iloc[0]

        wh_list = list(set(wh_lookup.get(selected_code, [])))

        primary_present = [wh for wh in PRIMARY_WAREHOUSES if wh in wh_list]
        secondary = [wh for wh in wh_list if wh not in PRIMARY_WAREHOUSES]

        wh_sorted = primary_present + sorted(secondary)

        selected_wh = st.selectbox(
            "Warehouse",
            wh_sorted,
            index=0 if wh_sorted else 0,
            key=f"wh_{idx}"
        )

        if not primary_present:
            st.warning("⚠ Not available in primary warehouses")

        price = get_price(selected_code, item["price"])

        final_rows.append({

            "ITEM CODE": selected_code,
            "PRODUCT": row["PRODUCT"],
            "WH CODE": selected_wh,
            "STOCK": stock_lookup.get(selected_code, 0),
            "QUANTITY": item["qty"],
            "PRICE": price

        })

    if st.button("Confirm Selection"):

        df = pd.DataFrame(final_rows)

        df["AMOUNT"] = df["QUANTITY"] * df["PRICE"]

        st.session_state.final_df = df

# =====================================================
# DISPLAY TABLE
# =====================================================

if st.session_state.final_df is not None:

    edited_df = st.data_editor(
        st.session_state.final_df,
        use_container_width=True,
        key="po_editor"
    )

    edited_df.loc[:, "AMOUNT"] = edited_df["QUANTITY"] * edited_df["PRICE"]

    st.session_state.final_df = edited_df.copy()

    if st.button("🔄 Refresh Table"):
        st.rerun()

    subtotal = edited_df["AMOUNT"].sum()
    discount = subtotal * discount_rate
    gst = (subtotal - discount) * gst_rate
    total = subtotal - discount + gst

    colA, colB = st.columns([4,1])

    with colB:

        st.markdown(f"""
        <div style="text-align:right">
        Subtotal: ₹{subtotal:,.2f}<br>
        Discount ({discount_option}): ₹{discount:,.2f}<br>
        GST ({gst_option}): ₹{gst:,.2f}<br>
        <hr>
        <b>Total: ₹{total:,.2f}</b>
        </div>
        """, unsafe_allow_html=True)

    buffer = io.BytesIO()

    export_df = edited_df.copy()

    totals_df = pd.DataFrame({
        "PRICE": ["Subtotal", f"Discount ({discount_option})", f"GST ({gst_option})", "TOTAL"],
        "AMOUNT": [subtotal, discount, gst, total]
    })

    final_export = pd.concat([export_df, totals_df])

    final_export.to_excel(buffer, index=False)

    st.download_button("Download Purchase Order Excel", buffer.getvalue(), "PO.xlsx")
