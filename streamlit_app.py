import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import google.generativeai as genai
import os
import json
import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# --- 1. 頁面配置 ---
st.set_page_config(page_title="Alpha-Refinery 全球戰情室", layout="wide")
st.markdown("""
    <style>
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; border: 1px solid #f0f2f6; box-shadow: 2px 2px 5px rgba(0,0,0,0.05); }
    </style>
    """, unsafe_allow_html=True)

# --- 2. GDrive 下載函數 (解決「找不到資料庫」的核心) ---
def download_db_from_drive(db_name):
    try:
        # 這裡會讀取你在 Streamlit Cloud 設定的 Secrets
        info = json.loads(st.secrets["GDRIVE_SERVICE_ACCOUNT"])
        parent_id = st.secrets["PARENT_FOLDER_ID"]
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/drive']
        )
        service = build('drive', 'v3', credentials=creds)
        
        # 搜尋檔案
        query = f"name = '{db_name}' and '{parent_id}' in parents"
        results = service.files().list(q=query).execute()
        items = results.get('files', [])
        
        if not items: return False
        
        # 下載檔案
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

# --- 3. 市場切換與數據同步 ---
market_option = st.sidebar.selectbox("🚩 核心市場選擇", ("TW", "JP", "CN", "US", "HK", "KR"))
db_map = {
    "TW": "tw_stock_warehouse.db", 
    "JP": "jp_stock_warehouse.db", 
    "CN": "cn_stock_warehouse.db", 
    "US": "us_stock_warehouse.db", 
    "HK": "hk_stock_warehouse.db", 
    "KR": "kr_stock_warehouse.db"
}
target_db = db_map[market_option]

# 如果本地不存在資料庫，則從雲端下載
if not os.path.exists(target_db):
    with st.status(f"🔄 正在從雲端精煉廠同步 {market_option} 數據...", expanded=True):
        if download_db_from_drive(target_db):
            st.success("✅ 同步成功！")
            st.rerun()
        else:
            st.error(f"❌ 無法同步 {target_db}，請檢查 Secrets 設定或雲端檔案是否存在。")
            st.stop()

# --- 4. 主頁面邏輯 (已同步完成後才執行) ---
conn = sqlite3.connect(target_db)

try:
    latest_date = pd.read_sql("SELECT MAX(日期) FROM cleaned_daily_base", conn).iloc[0, 0]
    
    st.title(f"🚀 {market_option} 市場 Alpha 戰情室")
    st.caption(f"📅 基準日：{latest_date} | AI 助手：Gemini 1.5 Pro")

    # 抓取漲停數據
    query_today = f"""
    SELECT p.StockID, i.name as Name, i.sector as Sector, p.收盤, p.Ret_Day, p.Seq_LU_Count, p.is_limit_up
    FROM cleaned_daily_base p
    LEFT JOIN stock_info i ON p.StockID = i.symbol
    WHERE p.日期 = '{latest_date}' AND p.is_limit_up = 1
    ORDER BY p.Seq_LU_Count DESC, p.StockID ASC
    """
    df_today = pd.read_sql(query_today, conn)

    if df_today.empty:
        st.warning(f"⚠️ {latest_date} 此交易日尚無漲停數據。")
    else:
        # 第一部分：分佈圖
        st.divider()
        col1, col2 = st.columns([1.2, 1])
        with col1:
            df_today['Sector'] = df_today['Sector'].fillna('未分類')
            sector_counts = df_today['Sector'].value_counts().reset_index()
            sector_counts.columns = ['產業別', '漲停家數']
            fig = px.bar(sector_counts, x='漲停家數', y='產業別', orientation='h', color='漲停家數', color_continuous_scale='Reds')
            st.plotly_chart(fig, use_container_width=True)
        with col2:
            st.dataframe(df_today[['StockID', 'Name', 'Sector', 'Seq_LU_Count']], use_container_width=True, hide_index=True)

        # 第二部分：個股診斷
        st.divider()
        df_today['select_label'] = df_today['StockID'] + " " + df_today['Name'].fillna("")
        selected_label = st.selectbox("🎯 選擇今日漲停股進行精掃：", options=df_today['select_label'].tolist())
        
        if selected_label:
            target_id = selected_label.split(" ")[0]
            stock_detail = df_today[df_today['StockID'] == target_id].iloc[0]

            # 歷史回測
            backtest_q = f"SELECT COUNT(*) as total_lu, AVG(Overnight_Alpha) as avg_open, AVG(Next_1D_Max) as avg_max FROM cleaned_daily_base WHERE StockID = '{target_id}' AND Prev_LU = 1"
            bt = pd.read_sql(backtest_q, conn).iloc[0]

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("今日狀態", f"{stock_detail['Seq_LU_Count']} 連板")
            m2.metric("歷史漲停次數", f"{int(bt['total_lu'] or 0)} 次")
            m3.metric("隔日溢價期望", f"{(bt['avg_open'] or 0)*100:.2f}%")
            m4.metric("最高期望值", f"{(bt['avg_max'] or 0)*100:.2f}%")

            # 族群連動資訊
            current_sector = stock_detail['Sector']
            related_q = f"SELECT p.StockID, i.name as Name, p.is_limit_up FROM cleaned_daily_base p LEFT JOIN stock_info i ON p.StockID = i.symbol WHERE i.sector = '{current_sector}' AND p.日期 = '{latest_date}' AND p.StockID != '{target_id}' LIMIT 10"
            df_related = pd.read_sql(related_q, conn)
            related_stocks_str = "暫無同產業數據"
            if not df_related.empty:
                related_list = [f"{r['StockID']} {r['Name']}{'(亦漲停)' if r['is_limit_up']==1 else ''}" for _, r in df_related.iterrows()]
                related_stocks_str = "、".join(related_list)
            
            st.info(f"🌿 **同產業聯動狀態：** {related_stocks_str}")

            # --- 第三部分：AI 深度診斷 (強效超連結指令版) ---
            if st.button(f"🤖 啟動 Deep Scan：{stock_detail['Name']}"):
                api_key = st.secrets.get("GEMINI_API_KEY")
                if not api_key:
                    st.warning("⚠️ 請設定 GEMINI_API_KEY")
                else:
                    try:
                        # 定義連結格式
                        url_templates = {
                            "TW": "https://www.wantgoo.com/stock/{s}/technical-chart",
                            "US": "https://www.tradingview.com/symbols/{s}/",
                            "JP": "https://jp.tradingview.com/symbols/TSE-{s}/",
                            "CN": "https://panyi.eastmoney.com/pc_sc_kline.html?s={s}",
                            "HK": "https://www.tradingview.com/symbols/HKEX-{s}/",
                            "KR": "https://www.tradingview.com/symbols/KRX-{s}/"
                        }
                        current_url_base = url_templates.get(market_option, "https://google.com/search?q={s}")
                        clean_id = target_id.split('.')[0]

                        genai.configure(api_key=api_key)
                        all_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                        target_model = next((m for m in ['models/gemini-1.5-pro', 'models/gemini-1.5-flash'] if m in all_models), all_models[0])
                        model = genai.GenerativeModel(target_model)
                        
                        prompt = f"""
                        你是專業短線交易員。請分析股票 {selected_label}。
                        🚨 **指令：所有股票代號必須轉為 Markdown 連結** 🚨
                        格式：[代號 名稱]({current_url_base}) (代號需替換)
                        
                        分析重點：1.漲停原因 2.族群效應(參考：{related_stocks_str}) 3.連動預測 4.明日策略。
                        """
                        
                        with st.spinner("AI 深度掃描中..."):
                            response = model.generate_content(prompt)
                            st.success(f"### 🤖 AI Deep Scan 報告")
                            st.markdown(response.text)
                    except Exception as e:
                        st.error(f"AI 診斷失敗: {e}")

except Exception as e:
    st.error(f"載入失敗: {e}")
finally:
    conn.close()
