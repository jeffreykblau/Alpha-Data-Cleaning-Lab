import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import google.generativeai as genai

# 1. 網頁基本設定
st.set_page_config(page_title="Alpha 全球強勢股診斷站", layout="wide")
st.title("📊 全球股市漲停機率與 AI 深度診斷")

# 2. 側邊欄配置
st.sidebar.header("⚙️ 配置與篩選")
market_option = st.sidebar.selectbox(
    "選擇市場",
    ("TW", "JP", "CN", "US", "HK", "KR")
)
min_seq = st.sidebar.slider("最小連板/連漲次數", 1, 10, 1)

# 3. Google Drive & AI 配置 (從 Secrets 讀取)
@st.cache_data(show_spinner=False)
def download_db_from_drive(db_name):
    try:
        info = json.loads(st.secrets["GDRIVE_SERVICE_ACCOUNT"])
        parent_id = st.secrets["PARENT_FOLDER_ID"]
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/drive'])
        service = build('drive', 'v3', credentials=creds)
        query = f"name = '{db_name}' and '{parent_id}' in parents"
        results = service.files().list(q=query).execute()
        items = results.get('files', [])
        if not items: return False
        request = service.files().get_media(fileId=items[0]['id'])
        with open(db_name, 'wb') as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        return True
    except: return False

# 配置 Gemini
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    ai_model = genai.GenerativeModel('gemini-1.5-flash')

# 4. 主執行邏輯
db_map = {"TW":"tw_stock_warehouse.db","JP":"jp_stock_warehouse.db","CN":"cn_stock_warehouse.db","US":"us_stock_warehouse.db","HK":"hk_stock_warehouse.db","KR":"kr_stock_warehouse.db"}
target_db = db_map[market_option]

if not os.path.exists(target_db):
    with st.spinner(f"正在同步 {market_option} 數據庫..."):
        success = download_db_from_drive(target_db)
else: success = True

if success:
    conn = sqlite3.connect(target_db)
    
    # --- 區塊一：市場概況 ---
    query = f"SELECT p.*, i.name as 股名, i.sector as 行業 FROM cleaned_daily_base p LEFT JOIN stock_info i ON p.StockID = i.symbol WHERE p.日期 >= (SELECT date(MAX(日期), '-5 day') FROM cleaned_daily_base)"
    df = pd.read_sql(query, conn)
    df['日期'] = pd.to_datetime(df['日期']).dt.date
    
    df_lu = df[(df['is_limit_up'] == 1) & (df['Seq_LU_Count'] >= min_seq)].copy()
    
    col1, col2, col3 = st.columns(3)
    col1.metric("5日總樣本", f"{len(df):,}")
    col2.metric(f"強勢股家數", f"{len(df_lu):,}")
    col3.metric("市場熱度", f"{(len(df_lu)/len(df)*100):.2f}%" if len(df)>0 else "0%")

    tab1, tab2, tab3 = st.tabs(["🔥 行業熱點", "📋 強勢清單", "🔍 AI 個股診斷"])
    
    with tab1:
        if not df_lu.empty:
            fig = px.bar(df_lu['行業'].value_counts().reset_index(), x='count', y='行業', orientation='h', color='count')
            st.plotly_chart(fig, use_container_width=True)

    with tab2:
        st.dataframe(df_lu[['日期', 'StockID', '股名', '行業', '收盤', 'Seq_LU_Count']].sort_values('日期', ascending=False), use_container_width=True, hide_index=True)

    with tab3:
        st.subheader("個股歷史大數據分析")
        target_stock = st.text_input("輸入完整代碼 (如 2330.TW)", placeholder="2330.TW")
        
        if target_stock:
            # 撈取五年統計
            diag_q = f"SELECT COUNT(*) as total, SUM(is_limit_up) as lu, AVG(CASE WHEN Prev_LU=1 THEN Overnight_Alpha END) as ov, AVG(CASE WHEN Prev_LU=1 THEN Next_1D_Max END) as nxt FROM cleaned_daily_base WHERE StockID = '{target_stock}'"
            res = pd.read_sql(diag_q, conn).iloc[0]
            
            if res['total'] > 0:
                c1, c2, c3 = st.columns(3)
                c1.metric("歷史漲停次數", f"{int(res['lu'] or 0)} 次")
                c2.metric("隔日平均溢價", f"{(res['ov'] or 0)*100:.2f}%")
                c3.metric("隔日最高期望", f"{(res['nxt'] or 0)*100:.2f}%")
                
                # AI 按鈕
                if st.button("🚀 執行 AI 專家分析"):
                    prompt = f"你是量化專家。股票{target_stock}在{market_option}市場5年內漲停{res['lu']}次，漲停後隔日平均開盤溢價{(res['ov'] or 0)*100:.2f}%，隔日最高點平均{(res['nxt'] or 0)*100:.2f}%。請分析其慣性與操作風險。"
                    with st.spinner("AI 正在思考..."):
                        response = ai_model.generate_content(prompt)
                        st.markdown("---")
                        st.markdown(f"### 🤖 AI 診斷建議\n{response.text}")
            else: st.warning("找不到該代碼數據。")
    conn.close()
