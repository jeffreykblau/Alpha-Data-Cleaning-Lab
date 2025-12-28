# -*- coding: utf-8 -*-
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
st.set_page_config(page_title="Alpha-Refinery 全球戰情室", layout="wide", page_icon="🚀")

# --- 2. GDrive 同步函數 ---
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

# --- 3. 核心標題與「重大公告」 ---
st.title("🚀 全球漲停戰情室")

# 🔴 加入 AI 額度公告 (針對您提到的原因)
st.error("🚨 **系統重大公告：暫停 AI 詢問功能**")
st.markdown("""
由於發現 **Gemini 免費版 AI 額度被外部詢問頻率用光**，為了保護站長自用的研究額度，
目前已暫時將 **API Token 撤下**。在找到更好的解決方案（或更換 API 權限）前，
所有需要 AI 解說的功能將暫時停用，僅保留數據展示功能，敬請見諒。
""")

st.divider()

# 💡 市場切換提示
st.warning("💡 **操作提醒：** 切換市場時，請在側邊欄選取。系統下載該市場資料庫（約 1~3 分鐘）完成後，頁面將自動重新整理呈現最新數據。")

# --- 4. 市場切換邏輯 ---
market_option = st.sidebar.selectbox("🚩 核心市場選擇", ("TW", "JP", "CN", "US", "HK", "KR"))
db_map = {"TW":"tw_stock_warehouse.db", "JP":"jp_stock_warehouse.db", "CN":"cn_stock_warehouse.db", 
          "US":"us_stock_warehouse.db", "HK":"hk_stock_warehouse.db", "KR":"kr_stock_warehouse.db"}
target_db = db_map[market_option]

if not os.path.exists(target_db):
    with st.status(f"🔄 正在從雲端同步 {market_option} 數據...", expanded=True):
        if download_db_from_drive(target_db):
            st.success("✅ 同步完成！頁面即將跳轉。")
            st.rerun()
        else:
            st.error("❌ 同步失敗，請確認 Cloud 權限設定。")
            st.stop()

# --- 5. 數據讀取與視覺化 ---
if os.path.exists(target_db):
    conn = sqlite3.connect(target_db)
    try:
        # 獲取最新日期
        latest_date = pd.read_sql("SELECT MAX(日期) FROM cleaned_daily_base", conn).iloc[0,0]
        
        st.subheader(f"📍 當前分析市場：{market_option}")
        st.caption(f"📅 數據基準日：{latest_date} | 數據庫狀態：已連線 (SQLite)")

        # 查詢漲停股票
        query_today = f"""
        SELECT p.StockID, i.name as Name, i.sector as Sector, p.收盤, p.Ret_Day, p.Seq_LU_Count
        FROM cleaned_daily_base p
        LEFT JOIN stock_info i ON p.StockID = i.symbol
        WHERE p.日期 = '{latest_date}' AND p.is_limit_up = 1
        ORDER BY p.Seq_LU_Count DESC, p.StockID ASC
        """
        df_today = pd.read_sql(query_today, conn)

        if df_today.empty:
            st.warning(f"⚠️ {latest_date} 尚無漲停數據，這可能代表該市場今日尚未收盤或更新。")
        else:
            col1, col2 = st.columns([1.2, 1])
            
            with col1:
                st.subheader("📊 漲停產業分佈")
                df_today['Sector'] = df_today['Sector'].fillna('未分類')
                sector_counts = df_today['Sector'].value_counts().reset_index()
                sector_counts.columns = ['產業別', '漲停家數']
                
                fig = px.bar(
                    sector_counts, x='漲停家數', y='產業別', orientation='h', 
                    color='漲停家數', color_continuous_scale='Reds', text='漲停家數'
                )
                fig.update_layout(yaxis={'categoryorder':'total ascending'}, height=500)
                st.plotly_chart(fig, use_container_width=True)

            with col2:
                st.subheader("📋 強勢股清單")
                st.dataframe(
                    df_today[['StockID', 'Name', 'Sector', 'Seq_LU_Count']], 
                    use_container_width=True, hide_index=True, height=500
                )

            st.divider()
            st.info("🎯 數據展示正常。目前為「純淨模式」，AI 洞察功能暫停服務中。")

    except Exception as e:
        st.error(f"數據讀取失敗: {e}")
    finally:
        conn.close()
