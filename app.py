import streamlit as st
import pandas as pd
import io
import re
from rapidfuzz import fuzz

st.set_page_config(page_title="Purchase Order Generator", layout="wide")

st.title("Purchase Order Generator")

PRIMARY_WAREHOUSES = [
    "BWD_MAIN",
    "FBD_MAIN",
    "CHN_CENTRL",
    "KOL_MAIN"
]

# =====================================================
# SESSION STATE
# =====================================================

if "pattern_confirmed" not in st.session_state:
    st.session_state.pattern_confirmed = False

if "qty_index" not in st.session_state:
    st.session_state.qty_index = None

if "price_index" not in st.session_state:
    st.session_state.price_index = None

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
# LOAD SALES
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

# =====================================================
# CUSTOMER DROPDOWN
# =====================================================

selected_customer = st.selectbox("Customer", [""] + customer_list)

# =====================================================
# LOAD STOCK
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
# DISCOUNT GST
# =====================================================

col3, col4 = st.columns(2)

discount_option = col3.selectbox("Discount", ["3%", "2.5%", "0%"])
discount_rate = float(discount_option.replace("%",""))/100

gst_option = col4.selectbox("GST", ["0%", "5%", "12%", "18%", "28%"], index=3)
gst_rate = float(gst_option.replace("%",""))/100

# =====================================================
# FIND CANDIDATES
# =====================================================

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

# =====================================================
# PRICE ENGINE
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

    rows = sales_df[sales_df["ITEM CODE"] == item_code]

    if not rows.empty:
        return rows.iloc[0]["RATE"]

    return 0

# =====================================================
# DETECT NUMBERS
# =====================================================

def detect_numbers(line):

    return re.findall(r'\b\d+\b', line)

# =====================================================
# ORDER INPUT
# =====================================================

order_text = st.text_area("Enter Order")

lines = [l for l in order_text.split("\n") if l.strip()]

ambiguous_line = None
ambiguous_numbers = None

for line in lines:

    nums = detect_numbers(line)

    if len(nums) >= 2:
        ambiguous_line = line
        ambiguous_numbers = nums
        break

# =====================================================
# PATTERN CONFIRMATION UI
# =====================================================

if ambiguous_line and not st.session_state.pattern_confirmed:

    st.warning("Please confirm Quantity and Price positions")

    st.write("Example line:")
    st.code(ambiguous_line)

    qty_choice = st.selectbox(
        "Which number is Quantity?",
        ambiguous_numbers,
        key="qty_select"
    )

    price_choice = st.selectbox(
        "Which number is Price?",
        ["None"] + ambiguous_numbers,
        key="price_select"
    )

    if st.button("Confirm Pattern"):

        st.session_state.qty_index = ambiguous_numbers.index(qty_choice)

        if price_choice != "None":
            st.session_state.price_index = ambiguous_numbers.index(price_choice)
        else:
            st.session_state.price_index = None

        st.session_state.pattern_confirmed = True

        st.success("Pattern confirmed")

# =====================================================
# GENERATE PO
# =====================================================

if st.session_state.pattern_confirmed and st.button("Generate Purchase Order"):

    st.session_state.po_items = []

    for line in lines:

        nums = detect_numbers(line)

        qty = int(nums[st.session_state.qty_index]) if nums else 1

        price_override = None

        if st.session_state.price_index is not None and len(nums) > st.session_state.price_index:
            price_override = float(nums[st.session_state.price_index])

        product = line

        for n in nums:
            product = product.replace(n, "")

        candidates = find_candidates(product)

        st.session_state.po_items.append({
            "product": product,
            "qty": qty,
            "price": price_override,
            "candidates": candidates
        })

# =====================================================
# CONFIRM PRODUCTS
# =====================================================

if st.session_state.po_items:

    final_rows = []

    for i, item in enumerate(st.session_state.po_items):

        options = [
            f"{c['ITEM CODE']} | {c['PRODUCT']}"
            for c in item["candidates"]
        ]

        selected = st.selectbox("Product", options, key=f"prod{i}")

        code = selected.split("|")[0].strip()

        wh_list = list(set(wh_lookup.get(code, [])))

        primary = [w for w in PRIMARY_WAREHOUSES if w in wh_list]
        secondary = [w for w in wh_list if w not in PRIMARY_WAREHOUSES]

        wh_sorted = primary + sorted(secondary)

        wh = st.selectbox("Warehouse", wh_sorted, key=f"wh{i}")

        price = get_price(code, item["price"])

        final_rows.append({

            "ITEM CODE": code,
            "PRODUCT": selected,
            "WH CODE": wh,
            "STOCK": stock_lookup.get(code, 0),
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

    edited_df = st.data_editor(st.session_state.final_df, use_container_width=True)

    edited_df["AMOUNT"] = edited_df["QUANTITY"] * edited_df["PRICE"]

    st.session_state.final_df = edited_df.copy()

    if st.button("🔄 Refresh Table"):
        st.rerun()

    subtotal = edited_df["AMOUNT"].sum()

    discount = subtotal * discount_rate

    gst = (subtotal - discount) * gst_rate

    total = subtotal - discount + gst

    st.markdown(f"""
    **Subtotal:** ₹{subtotal:,.2f}  
    **Discount ({discount_option}):** ₹{discount:,.2f}  
    **GST ({gst_option}):** ₹{gst:,.2f}  
    ## Total: ₹{total:,.2f}
    """)

    buffer = io.BytesIO()

    export_df = edited_df.copy()

    totals = pd.DataFrame({
        "PRICE": ["Subtotal", f"Discount ({discount_option})", f"GST ({gst_option})", "TOTAL"],
        "AMOUNT": [subtotal, discount, gst, total]
    })

    final_export = pd.concat([export_df, totals])

    final_export.to_excel(buffer, index=False)

    st.download_button("Download Excel", buffer.getvalue(), "PO.xlsx")
