import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import os
import io
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import google.generativeai as genai

# 1. 網頁基本設定
st.set_page_config(page_title="Alpha 全球強勢股診斷站", layout="wide")

# 2. 側邊欄配置
st.sidebar.header("⚙️ 全球市場配置")
market_option = st.sidebar.selectbox(
    "選擇追蹤市場",
    ("TW", "JP", "CN", "US", "HK", "KR")
)

# 3. 強化版 Google Drive 下載函數 (帶有錯誤回報與自動診斷)
def download_db_from_drive(db_name):
    try:
        if "GDRIVE_SERVICE_ACCOUNT" not in st.secrets:
            st.error("Secrets 中找不到 GDRIVE_SERVICE_ACCOUNT")
            return False
            
        info = json.loads(st.secrets["GDRIVE_SERVICE_ACCOUNT"])
        parent_id = st.secrets["PARENT_FOLDER_ID"]
        
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/drive'])
        service = build('drive', 'v3', credentials=creds)

        # 執行檔案搜尋
        query = f"name = '{db_name}' and '{parent_id}' in parents"
        results = service.files().list(q=query).execute()
        items = results.get('files', [])

        if not items:
            # 除錯提示：列出該資料夾內的所有檔名，確認是否大小寫不符
            all_files = service.files().list(q=f"'{parent_id}' in parents").execute().get('files', [])
            names = [f['name'] for f in all_files]
            st.error(f"❌ 找不到檔案: {db_name}")
            st.info(f"雲端資料夾內的現有檔案: {names}")
            return False

        # 執行下載
        file_id = items[0]['id']
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        
        with open(db_name, 'wb') as f:
            f.write(fh.getvalue())
        return True
    except Exception as e:
        st.error(f"下載過程中發生程式錯誤: {str(e)}")
        return False

# 4. 資料庫對應與同步
db_map = {
    "TW": "tw_stock_warehouse.db",
    "JP": "jp_stock_warehouse.db",
    "CN": "cn_stock_warehouse.db",
    "US": "us_stock_warehouse.db",
    "HK": "hk_stock_warehouse.db",
    "KR": "kr_stock_warehouse.db"
}
target_db = db_map[market_option]

if not os.path.exists(target_db):
    with st.status(f"🚀 正在同步 {market_option} 資料庫...", expanded=True) as status:
        if download_db_from_drive(target_db):
            status.update(label=f"✅ {market_option} 資料庫同步完成", state="complete", expanded=False)
        else:
            st.stop() # 下載失敗則停止運行

# 5. 資料連線與快取
conn = sqlite3.connect(target_db)

@st.cache_data
def get_stock_list(_target_db): # 傳入檔名作為 cache key
    local_conn = sqlite3.connect(_target_db)
    df = pd.read_sql("SELECT symbol, name FROM stock_info", local_conn)
    local_conn.close()
    return df

# 6. UI 佈局
st.title(f"📊 {market_option} 市場強勢股看板")
tab1, tab2 = st.tabs(["🔥 市場熱點分析", "🤖 AI 個股診斷"])

# --- Tab 1: 市場概況 ---
with tab1:
    st.subheader(f"{market_option} 市場最近 5 日趨勢")
    try:
        q = """
        SELECT p.日期, p.StockID, i.name as 股名, i.sector as 行業, p.收盤, p.Ret_Day, p.is_limit_up, p.Seq_LU_Count
        FROM cleaned_daily_base p
        LEFT JOIN stock_info i ON p.StockID = i.symbol
        WHERE p.日期 >= (SELECT date(MAX(日期), '-5 day') FROM cleaned_daily_base)
        """
        df_dash = pd.read_sql(q, conn)
        df_dash['日期'] = pd.to_datetime(df_dash['日期']).dt.date
        
        # 統計看板
        lu_df = df_dash[df_dash['is_limit_up'] == 1]
        c1, c2, c3 = st.columns(3)
        c1.metric("5日總樣本數", f"{len(df_dash):,}")
        c2.metric("強勢股家數", f"{len(lu_df):,}")
        c3.metric("市場熱度", f"{(len(lu_df)/len(df_dash)*100):.2f}%" if len(df_dash)>0 else "0%")

        if not lu_df.empty:
            fig = px.bar(lu_df['行業'].value_counts().reset_index(), x='count', y='行業', orientation='h', title="強勢行業排行")
            st.plotly_chart(fig, use_container_width=True)
            st.write("📋 強勢股明細 (Top 50)")
            st.dataframe(lu_df.sort_values('日期', ascending=False).head(50), hide_index=True)
    except Exception as e:
        st.warning(f"加載圖表時出錯: {e}")

# --- Tab 2: AI 診斷 (搜尋功能優化) ---
with tab2:
    st.subheader("🔍 個股大數據診斷")
    
    try:
        stocks = get_stock_list(target_db)
        stocks['display'] = stocks['symbol'] + " " + stocks['name']
        
        selected_stock = st.selectbox(
            "請輸入或選擇股票代碼 (例如輸入 1 會自動篩選)",
            options=stocks['display'].tolist(),
            index=None,
            placeholder="請搜尋..."
        )

        if selected_stock:
            target_symbol = selected_stock.split(" ")[0]
            
            # 歷史大數據統計
            diag_q = f"""
            SELECT COUNT(*) as total, SUM(is_limit_up) as lu, 
            AVG(CASE WHEN Prev_LU=1 THEN Overnight_Alpha END) as ov, 
            AVG(CASE WHEN Prev_LU=1 THEN Next_1D_Max END) as nxt 
            FROM cleaned_daily_base WHERE StockID = '{target_symbol}'
            """
            res = pd.read_sql(diag_q, conn).iloc[0]
            
            if res['total'] > 0:
                st.write(f"### {selected_stock} 歷史統計 (5年)")
                c1, c2, c3 = st.columns(3)
                c1.metric("漲停/大漲次數", f"{int(res['lu'] or 0)} 次")
                c2.metric("隔日開盤溢價均值", f"{(res['ov'] or 0)*100:.2f}%")
                c3.metric("隔日最高期望值", f"{(res['nxt'] or 0)*100:.2f}%")
                
                # AI 分析按鈕
                if st.button("🚀 執行 Gemini AI 專家分析"):
                    if "GEMINI_API_KEY" in st.secrets:
                        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                        model = genai.GenerativeModel('gemini-1.5-flash')
                        
                        analysis_prompt = f"""
                        你是量化分析專家。股票 {selected_stock} 在過去5年的數據如下：
                        - 總漲停/大漲次數：{res['lu']} 次
                        - 漲停後隔日開盤平均溢價：{(res['ov'] or 0)*100:.2f}%
                        - 漲停後隔日盤中最高價平均期望：{(res['nxt'] or 0)*100:.2f}%
                        請根據數據分析其隔日沖慣性，並給予投資建議與操作風險評估。
                        """
                        
                        with st.spinner("Gemini 正在計算分析..."):
                            response = model.generate_content(analysis_prompt)
                            st.markdown("---")
                            st.markdown(f"### 🤖 AI 專家診斷報告\n{response.text}")
                    else:
                        st.error("請在 Secrets 中設定 GEMINI_API_KEY")
            else:
                st.warning("該股票在資料庫中無足夠歷史數據。")
    except Exception as e:
        st.error(f"搜尋功能載入失敗: {e}")

conn.close()
