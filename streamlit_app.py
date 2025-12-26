import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import os
import json
import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# --- 1. 頁面配置 ---
st.set_page_config(page_title="Alpha-Refinery 全球戰情室", layout="wide")

# --- 2. GDrive 同步函數 (GitHub 部署必備) ---
def download_db_from_drive(db_name):
    try:
        info = json.loads(st.secrets["GDRIVE_SERVICE_ACCOUNT"])
        parent_id = st.secrets["PARENT_FOLDER_ID"]
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/drive']
        )
        service = build('drive', 'v3', credentials=creds)
        query = f"name = '{db_name}' and '{parent_id}' in parents"
        results = service.files().list(q=query).execute()
        items = results.get('files', [])
        if not items: return False
        request = service.files().get_media(fileId=items[0]['id'])
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        with open(db_name, 'wb') as f: f.write(fh.getvalue())
        return True
    except: return False

# --- 3. 市場切換與同步邏輯 ---
market_option = st.sidebar.selectbox("🚩 核心市場選擇", ("TW", "JP", "CN", "US", "HK", "KR"))
db_map = {"TW":"tw_stock_warehouse.db", "JP":"jp_stock_warehouse.db", "CN":"cn_stock_warehouse.db", 
          "US":"us_stock_warehouse.db", "HK":"hk_stock_warehouse.db", "KR":"kr_stock_warehouse.db"}
target_db = db_map[market_option]

if not os.path.exists(target_db):
    with st.status(f"🔄 正在從雲端精煉廠同步 {market_option} 數據...", expanded=True):
        if download_db_from_drive(target_db):
            st.success("同步成功！")
            st.rerun()
        else:
            st.error("同步失敗，請檢查權限。")
            st.stop()

# --- 4. 經典版戰情室佈局 ---
conn = sqlite3.connect(target_db)
try:
    # 獲取最新日期
    latest_date = pd.read_sql("SELECT MAX(日期) FROM cleaned_daily_base", conn).iloc[0,0]
    
    # A. 標題與基準日 (回歸你要求的格式)
    st.title(f"🚀 {market_option} 今日漲停戰情室")
    st.caption(f"📅 基準日：{latest_date} | AI 分析助手：Gemini 1.5 系列")

    # B. 抓取今日漲停數據
    query_today = f"""
    SELECT p.StockID, i.name as Name, i.sector as Sector, p.收盤, p.Ret_Day, p.Seq_LU_Count
    FROM cleaned_daily_base p
    LEFT JOIN stock_info i ON p.StockID = i.symbol
    WHERE p.日期 = '{latest_date}' AND p.is_limit_up = 1
    ORDER BY p.Seq_LU_Count DESC, p.StockID ASC
    """
    df_today = pd.read_sql(query_today, conn)

    if df_today.empty:
        st.warning(f"⚠️ {latest_date} 尚無漲停數據。")
    else:
        st.divider()
        
        # C. 左右分欄：左邊圖表，右邊清單 (這是最經典好看的版型)
        col1, col2 = st.columns([1.2, 1])
        
        with col1:
            st.subheader("📊 漲停產業別分佈")
            df_today['Sector'] = df_today['Sector'].fillna('未分類')
            sector_counts = df_today['Sector'].value_counts().reset_index()
            sector_counts.columns = ['產業別', '漲停家數']
            
            fig = px.bar(
                sector_counts, 
                x='漲停家數', 
                y='產業別', 
                orientation='h', 
                color='漲停家數', 
                color_continuous_scale='Reds',
                text='漲停家數'
            )
            fig.update_layout(yaxis={'categoryorder':'total ascending'}, showlegend=False, height=500)
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.subheader("📋 今日強勢清單")
            # 調整 DataFrame 顯示，移除 Index，讓視覺更乾淨
            st.dataframe(
                df_today[['StockID', 'Name', 'Sector', 'Seq_LU_Count']], 
                use_container_width=True, 
                hide_index=True,
                height=500
            )

        st.divider()
        st.info("💡 提示：如需針對特定個股進行 AI 深度診斷，請從左側選單進入 **Deep Scan** 頁面。")

except Exception as e:
    st.error(f"數據讀取失敗: {e}")
finally:
    conn.close()
