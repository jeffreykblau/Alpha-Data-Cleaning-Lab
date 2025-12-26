import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import google.generativeai as genai
import os

# 1. 頁面配置
st.set_page_config(page_title="今日漲停與產業熱度", layout="wide")

# 2. 側邊欄與資料庫連線
market_option = st.sidebar.selectbox("🚩 選擇市場", ("TW", "JP", "CN", "US", "HK", "KR"), key="today_market")
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
    st.error(f"請先回到首頁同步 {market_option} 數據庫")
    st.stop()

# 核心數據讀取
conn = sqlite3.connect(target_db)

try:
    # A. 找出最新交易日
    latest_date = pd.read_sql("SELECT MAX(日期) FROM cleaned_daily_base", conn).iloc[0, 0]
    
    # B. 抓取當天漲停的所有股票及產業
    query_today = f"""
    SELECT p.StockID, i.name as Name, i.sector as Sector, p.收盤, p.Ret_Day
    FROM cleaned_daily_base p
    LEFT JOIN stock_info i ON p.StockID = i.symbol
    WHERE p.日期 = '{latest_date}' AND p.is_limit_up = 1
    """
    df_today = pd.read_sql(query_today, conn)

    st.title(f"🔥 {market_option} 今日漲停強勢榜")
    st.write(f"📅 數據基準日：{latest_date} (最新交易日)")

    if df_today.empty:
        st.warning("今日尚無漲停股票數據。")
    else:
        # --- 佈局一：產業別統計圖 ---
        st.divider()
        col_chart, col_list = st.columns([1, 1])
        
        with col_chart:
            st.subheader("📊 漲停產業別統計")
            sector_counts = df_today['Sector'].value_counts().reset_index()
            sector_counts.columns = ['產業別', '漲停家數']
            fig = px.bar(sector_counts, x='漲停家數', y='產業別', orientation='h', 
                         color='漲停家數', color_continuous_scale='Reds')
            st.plotly_chart(fig, use_container_width=True)

        with col_list:
            st.subheader("📋 今日漲停清單")
            st.dataframe(df_today[['StockID', 'Name', 'Sector', '收盤']], use_container_width=True, hide_index=True)

        # --- 佈局二：個股深入分析選單 ---
        st.divider()
        st.subheader("🔍 今日強勢股回測與 AI 診斷")
        
        # 下拉選單：僅列出今日漲停的股票
        df_today['display'] = df_today['StockID'] + " " + df_today['Name']
        selected_stock = st.selectbox("選擇今日漲停股進行深入分析", options=df_today['display'].tolist())

        if selected_stock:
            target_symbol = selected_stock.split(" ")[0]
            
            # 抓取該股 5 年妖性統計 (與 Deep Scan 邏輯一致)
            hist_q = f"""
            SELECT COUNT(*) as t, SUM(is_limit_up) as lu, 
            AVG(CASE WHEN Prev_LU=1 THEN Overnight_Alpha END) as ov,
            AVG(CASE WHEN Prev_LU=1 THEN Next_1D_Max END) as nxt
            FROM cleaned_daily_base WHERE StockID = '{target_symbol}'
            """
            hist = pd.read_sql(hist_q, conn).iloc[0]
            
            # 顯示該股回測數據
            c1, c2, c3 = st.columns(3)
            c1.metric("5年漲停次數", f"{int(hist['lu'] or 0)} 次")
            c2.metric("隔日開盤溢價期望", f"{(hist['ov'] or 0)*100:.2f}%")
            c3.metric("盤中最高期望", f"{(hist['nxt'] or 0)*100:.2f}%")

            # --- AI 概念股與漲停原因分析 ---
            if st.button(f"🚀 詢問 AI：為何 {selected_stock} 會漲停？"):
                if "GEMINI_API_KEY" in st.secrets:
                    try:
                        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                        # 模型偵測與選擇
                        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                        target_model = 'models/gemini-1.5-flash' if 'models/gemini-1.5-flash' in available_models else available_models[0]
                        model = genai.GenerativeModel(target_model)
                        
                        prompt = f"""
                        你是一位資深股市分析師。針對今日漲停的股票 {selected_stock}（產業：{df_today[df_today['StockID']==target_symbol]['Sector'].values[0]}），請回答：
                        1. 這檔股票屬於哪些熱門概念股？
                        2. 根據目前市場趨勢，分析其今天漲停的可能原因（如：產業利多、財報、技術面突破或題材炒作）。
                        3. 該股歷史上漲停後的隔日溢價為 {(hist['ov'] or 0)*100:.2f}%，請評價明天的續航力。
                        """
                        
                        with st.spinner("AI 正在分析新聞與市場熱度..."):
                            response = model.generate_content(prompt)
                            st.info(f"### 🤖 AI 深度分析：{selected_stock}")
                            st.markdown(response.text)
                    except Exception as e:
                        st.error(f"AI 分析失敗: {e}")
                else:
                    st.warning("請在 Secrets 中設定 GEMINI_API_KEY")

except Exception as e:
    st.error(f"數據讀取失敗: {e}")

finally:
    conn.close()
