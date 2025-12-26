import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import google.generativeai as genai
import os
import re  # 正規表達式必備
import json
import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# --- 1. 頁面配置 ---
st.set_page_config(page_title="全球漲停板 AI 分析儀", layout="wide")

# --- 2. GDrive 自動下載函數 (解決「找不到資料庫」的核心) ---
def download_db_from_drive(db_name):
    try:
        # 請確保在 Streamlit Secrets 有設定這兩個值
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
        while not done:
            _, done = downloader.next_chunk()
        
        with open(db_name, 'wb') as f:
            f.write(fh.getvalue())
        return True
    except Exception as e:
        st.error(f"❌ 雲端下載失敗: {e}")
        return False

# --- 3. 市場與資料庫同步 ---
market_option = st.sidebar.selectbox("🚩 選擇分析市場", ("TW", "JP", "CN", "US", "HK", "KR"))
db_map = {
    "TW": "tw_stock_warehouse.db", 
    "JP": "jp_stock_warehouse.db", 
    "CN": "cn_stock_warehouse.db", 
    "US": "us_stock_warehouse.db", 
    "HK": "hk_stock_warehouse.db", 
    "KR": "kr_stock_warehouse.db"
}
target_db = db_map[market_option]

# 檢查檔案，不存在就下載
if not os.path.exists(target_db):
    with st.status(f"🔄 正在同步 {market_option} 資料庫..."):
        if download_db_from_drive(target_db):
            st.success("同步完成！")
            st.rerun()
        else:
            st.error(f"找不到檔案，請確認 {target_db} 已上傳至 Google Drive 指定資料夾。")
            st.stop()

# --- 4. 主程式邏輯 ---
conn = sqlite3.connect(target_db)

try:
    latest_date = pd.read_sql("SELECT MAX(日期) FROM cleaned_daily_base", conn).iloc[0, 0]
    query_today = f"""
    SELECT p.StockID, i.name as Name, i.sector as Sector, p.收盤, p.Ret_Day, p.Seq_LU_Count, p.is_limit_up
    FROM cleaned_daily_base p
    LEFT JOIN stock_info i ON p.StockID = i.symbol
    WHERE p.日期 = '{latest_date}' AND p.is_limit_up = 1
    ORDER BY p.Seq_LU_Count DESC, p.StockID ASC
    """
    df_today = pd.read_sql(query_today, conn)

    st.title(f"🚀 {market_option} 今日漲停戰情室")
    
    if not df_today.empty:
        # 顯示產業圖表與清單 (略，維持原本代碼即可)
        st.dataframe(df_today[['StockID', 'Name', 'Sector', 'Seq_LU_Count']], use_container_width=True)

        st.divider()
        df_today['select_label'] = df_today['StockID'] + " " + df_today['Name'].fillna("")
        selected_label = st.selectbox("🎯 選擇分析對象：", options=df_today['select_label'].tolist())
        
        if selected_label:
            target_id = selected_label.split(" ")[0]
            stock_detail = df_today[df_today['StockID'] == target_id].iloc[0]
            
            # 獲取同族群資料做為 AI 參考
            related_q = f"SELECT p.StockID, i.name as Name FROM cleaned_daily_base p LEFT JOIN stock_info i ON p.StockID = i.symbol WHERE i.sector = '{stock_detail['Sector']}' AND p.日期 = '{latest_date}' AND p.StockID != '{target_id}' LIMIT 5"
            df_related = pd.read_sql(related_q, conn)
            related_stocks_str = "、".join([f"{r['StockID']} {r['Name']}" for _, r in df_related.iterrows()]) if not df_related.empty else "尚無同產業股"

            # --- 第三部分：AI 深度診斷 (這是你要求的強制轉換連結版) ---
            if st.button(f"🤖 啟動 Deep Scan：{stock_detail['Name']}"):
                api_key = st.secrets.get("GEMINI_API_KEY")
                if not api_key:
                    st.warning("⚠️ 請設定 GEMINI_API_KEY")
                else:
                    try:
                        url_templates = {
                            "TW": "https://www.wantgoo.com/stock/{s}/technical-chart",
                            "US": "https://www.tradingview.com/symbols/{s}/",
                            "JP": "https://jp.tradingview.com/symbols/TSE-{s}/",
                            "CN": "https://panyi.eastmoney.com/pc_sc_kline.html?s={s}",
                            "HK": "https://www.tradingview.com/symbols/HKEX-{s}/",
                            "KR": "https://www.tradingview.com/symbols/KRX-{s}/"
                        }
                        current_url_base = url_templates.get(market_option, "https://google.com/search?q={s}")

                        genai.configure(api_key=api_key)
                        model = genai.GenerativeModel('gemini-1.5-pro')
                        
                        prompt = f"""分析股票 {selected_label}：產業為{stock_detail['Sector']}，今日第{stock_detail['Seq_LU_Count']}天漲停。
                        同族群參考：{related_stocks_str}
                        請分析：1.核心題材 2.族群效應 3.誰最具有聯動性 4.明日策略。"""
                        
                        with st.spinner("AI 深度掃描中..."):
                            response = model.generate_content(prompt)
                            full_text = response.text

                            # 🚀 Regex 替換邏輯 (不管 AI 怎麼寫，看到代號就換連結)
                            pattern = r"(\d{3,6})\.(TW|TWO|SS|SZ|T|HK|KS)"
                            def replace_with_link(match):
                                code = match.group(1)
                                full_match = match.group(0)
                                url = current_url_base.format(s=code)
                                return f"[{full_match}]({url})"

                            linked_text = re.sub(pattern, replace_with_link, full_text)
                            st.success(f"### 🤖 AI Deep Scan 報告")
                            st.markdown(linked_text)
                    except Exception as e:
                        st.error(f"AI 診斷失敗: {e}")

except Exception as e:
    st.error(f"錯誤: {e}")
finally:
    conn.close()
