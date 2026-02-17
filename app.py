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
# MODERN CLEAN UI CSS
# =====================================================

st.markdown("""
<style>

.stApp {
    background-color: #f5f7fb;
}

.main-title {
    font-size: 28px;
    font-weight: 600;
    margin-bottom: 20px;
}

.section-card {
    background: white;
    padding: 20px;
    border-radius: 10px;
    border: 1px solid #e5e7eb;
    margin-bottom: 15px;
}

.section-title {
    font-size: 18px;
    font-weight: 600;
    margin-bottom: 10px;
}

.totals-card {
    background: white;
    padding: 18px;
    border-radius: 10px;
    border: 1px solid #e5e7eb;
    width: 300px;
    float: right;
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

</style>
""", unsafe_allow_html=True)

# =====================================================
# HEADER
# =====================================================

st.markdown('<div class="main-title">Purchase Order System</div>', unsafe_allow_html=True)

# =====================================================
# SESSION STATE
# =====================================================

if "po_items" not in st.session_state:
    st.session_state.po_items = []

if "final_df" not in st.session_state:
    st.session_state.final_df = None

PRIMARY_WH = ["BWD_MAIN","FBD_MAIN","CHN_CENTRL","KOL_MAIN"]

# =====================================================
# DATA SOURCE
# =====================================================

st.markdown('<div class="section-card">', unsafe_allow_html=True)
st.markdown('<div class="section-title">Data Source</div>', unsafe_allow_html=True)

col1,col2=st.columns(2)

sales_file=col1.file_uploader("Sales Register",type=["xlsx"])
stock_file=col2.file_uploader("Stock Report",type=["xlsx"])

st.markdown('</div>', unsafe_allow_html=True)

if not sales_file or not stock_file:
    st.stop()

# =====================================================
# LOAD DATA
# =====================================================

@st.cache_data
_attachment
def load_sales(file):

    df=pd.read_excel(file,sheet_name="data")

    df.columns=df.columns.str.strip()

    df["ITEM CODE"]=df["Item Code"].astype(str).str.upper()
    df["PRODUCT"]=df["Product"].fillna("").astype(str).str.upper()
    df["CUSTOMER"]=df["Customer Name"].fillna("").astype(str).str.upper()
    df["RATE"]=df["Rate"].astype(float)

    df["SEARCH"]=df["ITEM CODE"]+" "+df["PRODUCT"]

    df=df.sort_values("Invoice Date",ascending=False)

    unique=df.drop_duplicates("ITEM CODE")

    customers=sorted(df["CUSTOMER"].unique())

    return df,unique,customers

sales_df,unique_products,customers=load_sales(sales_file)

@st.cache_data
def load_stock(file):

    df=pd.read_excel(file)

    df.columns=df.columns.str.strip().str.upper()

    df["ITEM CODE"]=df["ITEM CODE"].astype(str).str.upper()
    df["TOTAL QTY"]=df["TOTAL QTY"].astype(float)
    df["WH CODE"]=df["WH CODE"].astype(str)

    return df

stock_df=load_stock(stock_file)

stock_lookup=stock_df.groupby("ITEM CODE")["TOTAL QTY"].sum().to_dict()
wh_lookup=stock_df.groupby("ITEM CODE")["WH CODE"].apply(list).to_dict()

# =====================================================
# CUSTOMER SETTINGS
# =====================================================

st.markdown('<div class="section-card">', unsafe_allow_html=True)
st.markdown('<div class="section-title">Customer & Settings</div>', unsafe_allow_html=True)

col1,col2,col3=st.columns(3)

selected_customer=col1.selectbox("Customer",[""]+customers)
discount_option=col2.selectbox("Discount",["3%","2.5%","0%"])
gst_option=col3.selectbox("GST",["0%","5%","12%","18%","28%"],index=3)

st.markdown('</div>', unsafe_allow_html=True)

discount_rate=float(discount_option.replace("%",""))/100
gst_rate=float(gst_option.replace("%",""))/100

# =====================================================
# ORDER INPUT
# =====================================================

st.markdown('<div class="section-card">', unsafe_allow_html=True)
st.markdown('<div class="section-title">Enter Order</div>', unsafe_allow_html=True)

order_text=st.text_area("",height=150)

generate=st.button("Generate Purchase Order")

st.markdown('</div>', unsafe_allow_html=True)

# =====================================================
# HELPERS
# =====================================================

def detect_numbers(line):
    return re.findall(r'\d+\.?\d*',line)

def find_candidates(query):

    query=query.upper()
    results=[]

    for _,row in unique_products.iterrows():

        score=fuzz.partial_ratio(query,row["SEARCH"])

        if score>60:

            results.append({
                "ITEM CODE":row["ITEM CODE"],
                "PRODUCT":row["PRODUCT"]
            })

    return results[:20]

def get_price(code,override):

    if override:
        return override

    if selected_customer:

        rows=sales_df[
            (sales_df["ITEM CODE"]==code)&
            (sales_df["CUSTOMER"]==selected_customer)
        ]

        if not rows.empty:
            return rows.iloc[0]["RATE"]

    rows=sales_df[sales_df["ITEM CODE"]==code]

    if not rows.empty:
        return rows.iloc[0]["RATE"]

    return 0

# =====================================================
# GENERATE ITEMS
# =====================================================

if generate:

    st.session_state.po_items=[]

    lines=[l for l in order_text.split("\n") if l.strip()]

    for line in lines:

        nums=detect_numbers(line)

        qty=int(float(nums[0])) if nums else 1
        price_override=float(nums[-1]) if len(nums)>=2 else None

        product=line

        for n in nums:
            product=product.replace(n,"")

        candidates=find_candidates(product)

        st.session_state.po_items.append({
            "raw":line,
            "qty":qty,
            "price":price_override,
            "candidates":candidates
        })

# =====================================================
# CONFIRM PRODUCTS
# =====================================================

if st.session_state.po_items:

    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Confirm Products</div>', unsafe_allow_html=True)

    rows=[]

    for i,item in enumerate(st.session_state.po_items):

        st.subheader(item["raw"])

        options=[f"{c['ITEM CODE']} | {c['PRODUCT']}" for c in item["candidates"]]

        selected=st.selectbox("Product",options,key=i)

        code=selected.split("|")[0]

        wh_list=wh_lookup.get(code,[])

        primary=[w for w in PRIMARY_WH if w in wh_list]
        secondary=[w for w in wh_list if w not in PRIMARY_WH]

        wh_sorted=primary+sorted(secondary)

        wh=st.selectbox("Warehouse",wh_sorted,key=f"wh{i}")

        price=get_price(code,item["price"])

        rows.append({
            "ITEM CODE":code,
            "PRODUCT":selected,
            "WH CODE":wh,
            "STOCK":stock_lookup.get(code,0),
            "QUANTITY":item["qty"],
            "PRICE":price,
            "AMOUNT":price*item["qty"]
        })

    if st.button("Confirm Selection"):
        st.session_state.final_df=pd.DataFrame(rows)

    st.markdown('</div>', unsafe_allow_html=True)

# =====================================================
# TABLE + TOTALS
# =====================================================

if st.session_state.final_df is not None:

    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Purchase Order</div>', unsafe_allow_html=True)

    edited=st.data_editor(st.session_state.final_df,use_container_width=True)

    edited["AMOUNT"]=edited["QUANTITY"]*edited["PRICE"]

    st.session_state.final_df=edited

    subtotal=edited["AMOUNT"].sum()
    discount=subtotal*discount_rate
    gst=(subtotal-discount)*gst_rate
    total=subtotal-discount+gst

    st.markdown('</div>', unsafe_allow_html=True)

    # totals card below right
    col1,col2=st.columns([5,1])

    with col2:

        st.markdown(f"""
<div class="totals-card">

<div class="total-line">
<span>Subtotal</span>
<span>₹{subtotal:,.2f}</span>
</div>

<div class="total-line">
<span>Discount ({discount_option})</span>
<span>₹{discount:,.2f}</span>
</div>

<div class="total-line">
<span>GST ({gst_option})</span>
<span>₹{gst:,.2f}</span>
</div>

<hr>

<div class="total-line total-final">
<span>Total</span>
<span>₹{total:,.2f}</span>
</div>

</div>
""",unsafe_allow_html=True)

    # download button
    buffer=io.BytesIO()

    export=edited.copy()

    totals=pd.DataFrame({
        "PRICE":["Subtotal",f"Discount ({discount_option})",f"GST ({gst_option})","TOTAL"],
        "AMOUNT":[subtotal,discount,gst,total]
    })

    final_export=pd.concat([export,totals])

    final_export.to_excel(buffer,index=False)

    st.download_button("Download PO Excel",buffer.getvalue(),"Purchase_Order.xlsx")
