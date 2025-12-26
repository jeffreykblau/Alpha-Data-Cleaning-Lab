import streamlit as st
import sqlite3
import pandas as pd
import os
import json
import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

st.set_page_config(page_title="Alpha-Refinery 全球戰情室", layout="wide")

# --- GDrive 下載函數 (保持不變) ---
def download_db_from_drive(db_name):
    try:
        info = json.loads(st.secrets["GDRIVE_SERVICE_ACCOUNT"])
        parent_id = st.secrets["PARENT_FOLDER_ID"]
        creds = service_account.Credentials.from_service_account_info(info, scopes=['https://www.googleapis.com/auth/drive'])
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

# --- 市場切換 ---
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
            st.error("同步失敗，請檢查權限設定。")
            st.stop()

# --- 主頁內容 ---
st.title(f"🚀 {market_option} 市場 Alpha 戰情室")
st.info("請從側邊欄選擇：\n1. Period Analysis (長短線趨勢)\n2. Risk Metrics (回撤與風險)\n3. Deep Scan (AI 綜合診斷)")

# 顯示簡單的最新市場熱度
conn = sqlite3.connect(target_db)
latest_date = pd.read_sql("SELECT MAX(日期) FROM cleaned_daily_base", conn).iloc[0,0]
st.write(f"📅 數據精煉基準日：{latest_date}")
conn.close()
