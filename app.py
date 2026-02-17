import streamlit as st
import pandas as pd
import io
import re
from rapidfuzz import fuzz

# =====================================================
# PAGE CONFIG
# =====================================================

st.set_page_config(page_title="Purchase Order System", layout="wide")

# =====================================================
# REAL MODERN CARD CSS (WORKS WITH STREAMLIT)
# =====================================================

st.markdown("""
<style>

.stApp {
    background-color: #f5f7fb;
}

.card {
    background: white;
    padding: 20px;
    border-radius: 12px;
    border: 1px solid #e5e7eb;
    margin-bottom: 16px;
}

.card-shadow {
    box-shadow: 0 4px 12px rgba(0,0,0,0.06);
}

.section-title {
    font-size: 18px;
    font-weight: 600;
    margin-bottom: 12px;
}

.main-header {
    font-size: 28px;
    font-weight: 600;
    margin-bottom: 12px;
}

.stock-green {color:#16a34a;font-weight:600;}
.stock-orange {color:#ea580c;font-weight:600;}
.stock-red {color:#dc2626;font-weight:600;}

</style>
""", unsafe_allow_html=True)

# =====================================================
# CARD HELPER FUNCTION (CRITICAL FIX)
# =====================================================

def card(title=None):
    container = st.container()
    with container:
        st.markdown('<div class="card card-shadow">', unsafe_allow_html=True)
        if title:
            st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)
    return container

def end_card():
    st.markdown('</div>', unsafe_allow_html=True)

# =====================================================
# HEADER
# =====================================================

st.markdown('<div class="main-header">Purchase Order System</div>', unsafe_allow_html=True)

# =====================================================
# SESSION STATE
# =====================================================

if "po_items" not in st.session_state:
    st.session_state.po_items = []

if "final_df" not in st.session_state:
    st.session_state.final_df = None

PRIMARY_WH = ["BWD_MAIN","FBD_MAIN","CHN_CENTRL","KOL_MAIN"]

# =====================================================
# DATA SOURCE CARD
# =====================================================

c = card("Data Source")

col1, col2 = st.columns(2)

sales_file = col1.file_uploader("Sales Register", type=["xlsx"])
stock_file = col2.file_uploader("Stock Report", type=["xlsx"])

end_card()

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
# LOAD STOCK (FIXED)
# =====================================================

@st.cache_data
def load_stock(file):

    df = pd.read_excel(file)

    df.columns = df.columns.str.strip().str.upper()

    df["ITEM CODE"] = df["ITEM CODE"].astype(str).str.upper()
    df["WH CODE"] = df["WH CODE"].astype(str).str.upper()
    df["TOTAL QTY"] = df["TOTAL QTY"].astype(float)

    return df

stock_df = load_stock(stock_file)

stock_lookup = stock_df.groupby("ITEM CODE")["TOTAL QTY"].sum().to_dict()
wh_lookup = stock_df.groupby("ITEM CODE")["WH CODE"].apply(list).to_dict()

# =====================================================
# CUSTOMER CARD
# =====================================================

card("Customer & Settings")

col1, col2, col3 = st.columns(3)

selected_customer = col1.selectbox("Customer", [""] + customer_list)

discount_option = col2.selectbox("Discount", ["3%","2.5%","0%"])

gst_option = col3.selectbox("GST", ["0%","5%","12%","18%","28%"], index=3)

end_card()

discount_rate = float(discount_option.replace("%",""))/100
gst_rate = float(gst_option.replace("%",""))/100

# =====================================================
# ORDER CARD
# =====================================================

card("Enter Order")

order_text = st.text_area("", height=150)

generate_clicked = st.button("Generate Purchase Order")

end_card()

# =====================================================
# HELPERS
# =====================================================

def detect_numbers(line):
    return re.findall(r'\d+\.?\d*', line)

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

    if override:
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
# GENERATE ITEMS
# =====================================================

if generate_clicked:

    st.session_state.po_items = []

    lines = [l for l in order_text.split("\n") if l.strip()]

    for line in lines:

        nums = detect_numbers(line)

        qty = int(float(nums[0])) if nums else 1

        price_override = float(nums[-1]) if len(nums)>=2 else None

        product = line

        for n in nums:
            product = product.replace(n,"")

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

    card("Confirm Products")

    final_rows=[]

    for i,item in enumerate(st.session_state.po_items):

        st.subheader(item["raw_line"])

        options=[f"{c['ITEM CODE']} | {c['PRODUCT']}" for c in item["candidates"]]

        selected=st.selectbox("Product",options,key=f"prod{i}")

        code=selected.split("|")[0].strip()

        wh_list=list(set(wh_lookup.get(code,[])))

        primary=[w for w in PRIMARY_WH if w in wh_list]
        secondary=[w for w in wh_list if w not in PRIMARY_WH]

        wh_sorted=primary+sorted(secondary)

        wh=st.selectbox("Warehouse",wh_sorted,key=f"wh{i}")

        stock=stock_lookup.get(code,0)

        if stock>5:
            st.markdown(f'<span class="stock-green">Stock: {stock}</span>',unsafe_allow_html=True)
        elif stock>0:
            st.markdown(f'<span class="stock-orange">Stock: {stock}</span>',unsafe_allow_html=True)
        else:
            st.markdown(f'<span class="stock-red">Stock: {stock}</span>',unsafe_allow_html=True)

        price=get_price(code,item["price"])

        final_rows.append({
            "ITEM CODE":code,
            "PRODUCT":selected,
            "WH CODE":wh,
            "STOCK":stock,
            "QUANTITY":item["qty"],
            "PRICE":price
        })

    confirm_clicked=st.button("Confirm Selection")

    end_card()

    if confirm_clicked:

        df=pd.DataFrame(final_rows)

        df["AMOUNT"]=df["QUANTITY"]*df["PRICE"]

        st.session_state.final_df=df

# =====================================================
# TABLE + TOTALS
# =====================================================

if st.session_state.final_df is not None:

    col1,col2=st.columns([4,1])

    with col1:

        card("Purchase Order")

        edited=st.data_editor(st.session_state.final_df,use_container_width=True)

        edited["AMOUNT"]=edited["QUANTITY"]*edited["PRICE"]

        st.session_state.final_df=edited

        end_card()

    subtotal=edited["AMOUNT"].sum()
    discount=subtotal*discount_rate
    gst=(subtotal-discount)*gst_rate
    total=subtotal-discount+gst

    with col2:

        card("Totals")

        st.markdown(f"""
Subtotal: ₹{subtotal:,.2f}

Discount ({discount_option}): ₹{discount:,.2f}

GST ({gst_option}): ₹{gst:,.2f}

---

**Total: ₹{total:,.2f}**
""")

        end_card()

    buffer=io.BytesIO()

    export=edited.copy()

    totals=pd.DataFrame({
        "PRICE":["Subtotal",f"Discount ({discount_option})",f"GST ({gst_option})","TOTAL"],
        "AMOUNT":[subtotal,discount,gst,total]
    })

    final_export=pd.concat([export,totals])

    final_export.to_excel(buffer,index=False)

    st.download_button("Download Excel",buffer.getvalue(),"PO.xlsx")
