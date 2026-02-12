import streamlit as st
import pandas as pd
import io
from rapidfuzz import fuzz

# =====================================================
# PAGE CONFIG
# =====================================================

st.set_page_config(page_title="Purchase Order Generator", layout="wide")
st.title("Purchase Order Generator")

PRIORITY_WH = ["BHIWANDI", "FARIDABAD", "CHENNAI", "KOLKATA"]

# =====================================================
# SESSION STATE INIT (SAFE)
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
# GST + DISCOUNT
# =====================================================

col3, col4 = st.columns(2)

discount_option = col3.selectbox("Discount", ["3%", "2.5%", "0%"], index=0)
discount_rate = float(discount_option.replace("%",""))/100

gst_option = col4.selectbox("GST", ["0%", "5%", "12%", "18%", "28%"], index=3)
gst_rate = float(gst_option.replace("%",""))/100

# =====================================================
# LOAD SALES REGISTER (OPTIMIZED FOR LARGE DATA)
# =====================================================

@st.cache_data
def load_sales(file):

    df = pd.read_excel(file, sheet_name="data")

    # normalize columns
    df.columns = df.columns.str.strip().str.upper()

    df["INVOICE DATE"] = pd.to_datetime(df["INVOICE DATE"])

    df["OEM"] = df["OEM"].fillna("").astype(str).str.upper()
    df["PRODUCT"] = df["PRODUCT"].fillna("").astype(str).str.upper()
    df["BRAND"] = df["BRAND"].fillna("").astype(str).str.upper()
    df["CATEGORY"] = df["CATEGORY"].fillna("").astype(str).str.upper()
    df["ITEM CODE"] = df["ITEM CODE"].fillna("").astype(str).str.upper()

    df["RATE"] = df["RATE"].astype(float)

    # MASTER SEARCH TEXT
    df["SEARCH_TEXT"] = (
        df["ITEM CODE"] + " " +
        df["OEM"] + " " +
        df["PRODUCT"] + " " +
        df["BRAND"] + " " +
        df["CATEGORY"]
    )

    df = df.sort_values("INVOICE DATE", ascending=False)

    # unique products by item code
    unique_df = df.drop_duplicates(subset=["ITEM CODE"])

    return df, unique_df

sales_df, unique_products = load_sales(sales_file)

# =====================================================
# LOAD STOCK
# =====================================================

@st.cache_data
def load_stock(file):

    df = pd.read_excel(file)

    df.columns = df.columns.str.strip().str.upper()

    df["ITEM CODE"] = df["ITEM CODE"].astype(str).str.upper()

    df["STOCK"] = df["TOTAL QTY"].astype(float)

    df["WH CODE"] = df["WH CODE"].astype(str)

    return df

stock_df = load_stock(stock_file)

stock_lookup = stock_df.groupby("ITEM CODE")["STOCK"].sum().to_dict()

wh_lookup = stock_df.groupby("ITEM CODE")["WH CODE"].apply(list).to_dict()

# =====================================================
# HIGH-ACCURACY SEARCH ENGINE (FIXED)
# =====================================================

def find_candidates(query):

    query = query.upper().strip()

    query_tokens = query.split()

    scored = []

    for _, row in unique_products.iterrows():

        text = row["SEARCH_TEXT"]

        # token match score
        token_score = sum(1 for token in query_tokens if token in text)

        # fuzzy backup score
        fuzzy_score = fuzz.partial_ratio(query, text)

        total_score = token_score * 100 + fuzzy_score

        if total_score > 80:

            scored.append((
                total_score,
                {
                    "ITEM CODE": row["ITEM CODE"],
                    "PRODUCT": row["PRODUCT"],
                    "OEM": row["OEM"]
                }
            ))

    scored.sort(reverse=True, key=lambda x: x[0])

    return [x[1] for x in scored[:30]]

# =====================================================
# PRICE FETCH (LATEST)
# =====================================================

def get_latest_price(item_code):

    row = sales_df[sales_df["ITEM CODE"] == item_code].iloc[0]

    return row["RATE"]

# =====================================================
# ORDER INPUT
# =====================================================

order_text = st.text_area("Enter Order")

if st.button("Generate Purchase Order"):

    st.session_state.po_items = []

    for line in order_text.split("\n"):

        parts = line.strip().split()

        if len(parts) < 2:
            continue

        try:
            qty = int(parts[0])
        except:
            continue

        query = " ".join(parts[1:])

        candidates = find_candidates(query)

        st.session_state.po_items.append({
            "query": query,
            "qty": qty,
            "candidates": candidates
        })

# =====================================================
# PRODUCT + WAREHOUSE CONFIRMATION
# =====================================================

if st.session_state.po_items:

    final_rows = []

    for idx, item in enumerate(st.session_state.po_items):

        st.subheader(f"Confirm Product: {item['query']}")

        options = [
            f"{c['ITEM CODE']} | {c['PRODUCT']}"
            for c in item["candidates"]
        ]

        options.append("Enter manually...")

        selected = st.selectbox(
            "Product",
            options,
            key=f"prod_{idx}"
        )

        if selected == "Enter manually...":

            manual_code = st.text_input(
                "Enter Item Code manually",
                key=f"manual_{idx}"
            ).upper()

            if manual_code == "":
                continue

            selected_code = manual_code

        else:

            selected_code = selected.split("|")[0].strip()

        if selected_code not in sales_df["ITEM CODE"].values:

            st.warning("Invalid Item Code")
            continue

        row = sales_df[sales_df["ITEM CODE"] == selected_code].iloc[0]

        wh_list = wh_lookup.get(selected_code, [""])

        wh_sorted = sorted(
            wh_list,
            key=lambda x: PRIORITY_WH.index(x) if x in PRIORITY_WH else 999
        )

        if len(wh_sorted) == 1:

            selected_wh = wh_sorted[0]

            st.info(f"WH auto-selected: {selected_wh}")

        else:

            selected_wh = st.selectbox(
                "Warehouse",
                wh_sorted,
                key=f"wh_{idx}"
            )

        final_rows.append({

            "ITEM CODE": selected_code,
            "OEM P/n.": row["OEM"],
            "PRODUCT": row["PRODUCT"],
            "WH CODE": selected_wh,
            "STOCK": stock_lookup.get(selected_code, 0),
            "QUANTITY": item["qty"],
            "PRICE": get_latest_price(selected_code)

        })

    if st.button("Confirm Selection"):

        df = pd.DataFrame(final_rows)

        df["AMOUNT"] = df["QUANTITY"] * df["PRICE"]

        st.session_state.final_df = df

# =====================================================
# DISPLAY EDITABLE PO TABLE (PERSISTENT)
# =====================================================

if st.session_state.final_df is not None:

    edited_df = st.data_editor(
        st.session_state.final_df,
        use_container_width=True,
        key="po_editor"
    )

    # live amount update
    edited_df["AMOUNT"] = edited_df["QUANTITY"] * edited_df["PRICE"]

    # save changes
    st.session_state.final_df = edited_df

    subtotal = edited_df["AMOUNT"].sum()

    discount = subtotal * discount_rate

    gst = (subtotal - discount) * gst_rate

    total = subtotal - discount + gst

    colA, colB = st.columns([4,1])

    with colB:

        st.markdown(f"""
        <div style="text-align:right;font-size:16px">
        Subtotal: ₹{subtotal:,.2f}<br>
        Discount: ₹{discount:,.2f}<br>
        GST: ₹{gst:,.2f}<br>
        <hr>
        <b style="font-size:24px">Total: ₹{total:,.2f}</b>
        </div>
        """, unsafe_allow_html=True)

    buffer = io.BytesIO()

    edited_df.to_excel(buffer, index=False)

    st.download_button(
        "Download Purchase Order Excel",
        buffer.getvalue(),
        "PO.xlsx"
    )
