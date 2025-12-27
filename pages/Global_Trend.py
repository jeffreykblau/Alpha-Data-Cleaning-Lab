import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import os
import io
import json
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.service_account import Credentials
import google.generativeai as genai

# --- 1. 頁面配置 ---
st.set_page_config(page_title="全球強勢股產業連動監測", layout="wide")

st.title("🌎 全球強勢股產業連動監測")
st.caption("同步追蹤六大市場漲幅 > 10% 之個股，偵測全球產業資金流向")

# --- 2. 市場與資料庫設定 ---
db_config = {
    "TW": "tw_stock_warehouse.db",
    "US": "us_stock_warehouse.db",
    "CN": "cn_stock_warehouse.db",
    "JP": "jp_stock_warehouse.db",
    "HK": "hk_stock_warehouse.db",
    "KR": "kr_stock_warehouse.db"
}

# --- 3. 自動下載邏輯 (解決缺檔問題) ---
def download_missing_dbs():
    creds_json = st.secrets.get("GDRIVE_SERVICE_ACCOUNT")
    if not creds_json:
        st.error("❌ 找不到 Google Drive 憑證 (GDRIVE_SERVICE_ACCOUNT)")
        return
    
    try:
        creds = Credentials.from_service_account_info(json.loads(creds_json))
        service = build('drive', 'v3', credentials=creds)
        
        for m_abbr, db_file in db_config.items():
            if not os.path.exists(db_file):
                with st.spinner(f"📥 正在從雲端同步 {m_abbr} 資料庫..."):
                    query = f"name = '{db_file}' and trashed = false"
                    results = service.files().list(q=query, fields="files(id, name)").execute()
                    files = results.get('files', [])
                    if files:
                        file_id = files[0]['id']
                        request = service.files().get_media(fileId=file_id)
                        fh = io.FileIO(db_file, 'wb')
                        downloader = MediaIoBaseDownload(fh, request)
                        done = False
                        while not done:
                            status, done = downloader.next_chunk()
                        st.sidebar.success(f"✅ {m_abbr} 同步成功")
                    else:
                        st.sidebar.warning(f"⚠️ 雲端找不到 {db_file}")
    except Exception as e:
        st.error(f"下載失敗: {e}")

# --- 側邊欄控制 ---
with st.sidebar:
    st.header("⚙️ 數據管理")
    if st.button("🚀 一鍵同步六國資料庫"):
        download_missing_dbs()
        st.cache_data.clear()
        st.rerun()
    
    st.divider()
    st.write("📁 本地檔案狀態：")
    available_markets = []
    for m_abbr, db_file in db_config.items():
        ready = os.path.exists(db_file)
        st.write(f"{'🟢' if ready else '🔴'} {m_abbr}")
        if ready: available_markets.append(m_abbr)

# --- 4. 數據抓取邏輯 ---
@st.cache_data(ttl=600)
def fetch_global_strong_stocks(markets):
    all_list = []
    for m in markets:
        db = db_config[m]
        conn = sqlite3.connect(db)
        try:
            # 獲取最新日
            latest = pd.read_sql("SELECT MAX(日期) FROM cleaned_daily_base", conn).iloc[0,0]
            # 篩選漲幅 >= 10% (包含台灣上市櫃與興櫃)
            query = f"""
            SELECT p.StockID, i.name as Name, i.sector as Sector, p.Ret_Day
            FROM cleaned_daily_base p
            LEFT JOIN stock_info i ON p.StockID = i.symbol
            WHERE p.日期 = '{latest}' AND p.Ret_Day >= 0.1
            """
            df = pd.read_sql(query, conn)
            df['Market'] = m
            all_list.append(df)
        except:
            pass
        finally:
            conn.close()
    return pd.concat(all_list, ignore_index=True) if all_list else pd.DataFrame()

# --- 5. 視覺化與分析 ---
if available_markets:
    global_df = fetch_global_strong_stocks(available_markets)
    
    if not global_df.empty:
        # 處理缺失產業
        global_df['Sector'] = global_df['Sector'].fillna('未分類/香港/興櫃')

        col_l, col_r = st.columns([1.2, 1])
        
        with col_l:
            st.subheader("📊 跨國強勢產業熱點")
            # 統計各產業在各國的家數
            chart_df = global_df.groupby(['Sector', 'Market']).size().reset_index(name='Count')
            fig = px.bar(
                chart_df, x='Count', y='Sector', color='Market', orientation='h',
                title="全球強勢個股產業分佈 (漲幅 > 10%)", barmode='stack',
                color_discrete_map={"TW": "#FF4B4B", "US": "#1C83E1", "CN": "#E11C1C", "JP": "#FFFFFF", "HK": "#FFD700", "KR": "#00FFCC"}
            )
            fig.update_layout(yaxis={'categoryorder':'total ascending'}, template="plotly_dark")
            st.plotly_chart(fig, use_container_width=True)

        with col_r:
            st.subheader("🔍 今日全球強勢榜")
            st.dataframe(
                global_df.sort_values(['Market', 'Ret_Day'], ascending=[True, False]),
                column_config={"Ret_Day": st.column_config.NumberColumn("漲幅", format="%.2f%%")},
                use_container_width=True, hide_index=True
            )

        # AI 趨勢分析
        st.divider()
        if st.button("🤖 啟動全球產業趨勢 AI 診斷"):
            api_key = st.secrets.get("GEMINI_API_KEY")
            if api_key:
                genai.configure(api_key=api_key)
                all_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                target_model = next((m for m in ['models/gemini-1.5-flash', 'gemini-1.5-flash'] if m in all_models), all_models[0])
                model = genai.GenerativeModel(target_model)
                
                # 準備 AI 提示詞
                sector_summary = global_df.groupby(['Sector', 'Market']).size().to_string()
                prompt = f"你是一位宏觀投資專家，請分析今日全球漲幅超過10%的股票分佈：\n{sector_summary}\n\n1. 哪些產業出現跨國聯動現象？\n2. 這些現象背後的全球趨勢為何？\n3. 風險建議。"
                
                with st.spinner("AI 正在比對數據..."):
                    response = model.generate_content(prompt)
                    st.info("### 🤖 全球趨勢分析報告")
                    st.markdown(response.text)
    else:
        st.warning("今日各國暫無漲幅 > 10% 的股票數據。")
else:
    st.error("請在側邊欄點擊「一鍵同步六國資料庫」以載入數據。")
