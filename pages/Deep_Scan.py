import streamlit as st
import sqlite3
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import google.generativeai as genai
import os
import re

st.set_page_config(page_title="AI 綜合個股深度掃描", layout="wide")

# 市場設定與資料庫對照
market_option = st.sidebar.selectbox("🚩 選擇市場", ("TW", "JP", "CN", "US", "HK", "KR"), key="scan_market")
db_map = {
    "TW": "tw_stock_warehouse.db", 
    "JP": "jp_stock_warehouse.db", 
    "CN": "cn_stock_warehouse.db", 
    "US": "us_stock_warehouse.db", 
    "HK": "hk_stock_warehouse.db", 
    "KR": "kr_stock_warehouse.db"
}
target_db = db_map[market_option]

url_templates = {
    "TW": "https://www.wantgoo.com/stock/{s}/technical-chart",
    "US": "https://www.tradingview.com/symbols/{s}/",
    "JP": "https://jp.tradingview.com/symbols/TSE-{s}/",
    "CN": "https://panyi.eastmoney.com/pc_sc_kline.html?s={s}",
    "HK": "https://www.tradingview.com/symbols/HKEX-{s}/",
    "KR": "https://www.tradingview.com/symbols/KRX-{s}/"
}
current_url_base = url_templates.get(market_option, "https://google.com/search?q={s}")

if not os.path.exists(target_db):
    st.error(f"請先回到首頁同步 {market_option} 數據庫")
    st.stop()

@st.cache_data
def get_full_stock_info(_db_path):
    conn = sqlite3.connect(_db_path)
    try:
        df = pd.read_sql("SELECT symbol, name, sector FROM stock_info", conn)
    except:
        df = pd.DataFrame(columns=['symbol', 'name', 'sector'])
    conn.close()
    return df

try:
    stock_df = get_full_stock_info(target_db)
    stock_df['display'] = stock_df['symbol'] + " " + stock_df['name']
    
    st.title("🔍 AI 綜合個股深度掃描")
    selected = st.selectbox("請搜尋代碼或名稱 (例如 2330)", options=stock_df['display'].tolist(), index=None)

    if selected:
        target_symbol = selected.split(" ")[0]
        conn = sqlite3.connect(target_db)
        
        # 1. 抓取最新一筆數據
        scan_q = f"SELECT * FROM cleaned_daily_base WHERE StockID = '{target_symbol}' ORDER BY 日期 DESC LIMIT 1"
        data_all = pd.read_sql(scan_q, conn)
        
        # 2. 歷史行為統計 (已修正為使用 Ret_High)
        hist_q = f"""
        SELECT COUNT(*) as t, SUM(is_limit_up) as lu, 
        SUM(CASE WHEN Prev_LU = 0 AND is_limit_up = 0 AND Ret_High > 0.095 THEN 1 ELSE 0 END) as failed_lu,
        AVG(CASE WHEN Prev_LU=1 THEN Overnight_Alpha END) as ov,
        AVG(CASE WHEN Prev_LU=1 THEN Next_1D_Max END) as nxt
        FROM cleaned_daily_base WHERE StockID = '{target_symbol}'
        """
        hist = pd.read_sql(hist_q, conn).iloc[0]

        # 3. 獲取產業與同業
        temp_info_q = f"SELECT sector FROM stock_info WHERE symbol = '{target_symbol}'"
        sector_res = pd.read_sql(temp_info_q, conn)
        sector_name = sector_res.iloc[0,0] if not sector_res.empty else "未知"
        
        peer_q = f"SELECT symbol, name FROM stock_info WHERE sector = '{sector_name}' AND symbol != '{target_symbol}' LIMIT 10"
        peers_df = pd.read_sql(peer_q, conn)
        conn.close()

        if not data_all.empty:
            data = data_all.iloc[0]
            st.divider()
            
            c_l, c_r = st.columns(2)
            with c_l:
                st.subheader("📊 多維度體質評分")
                # 計算雷達圖指標
                r5 = data.get('Ret_5D', 0) or 0
                r20 = data.get('Ret_20D', 0) or 0
                r200 = data.get('Ret_200D', 0) or 0
                vol = data.get('volatility_20d', 0) or 0
                dd = data.get('drawdown_after_high_20d', 0) or 0

                categories = ['短線動能', '中線動能', '長線動能', '抗震穩定度', '防禦力']
                # 歸一化評分邏輯
                plot_values = [
                    min(max(r5 * 5 + 0.5, 0.1), 1),
                    min(max(r20 * 2 + 0.5, 0.1), 1),
                    min(max(r200 + 0.5, 0.1), 1),
                    max(1 - vol * 2, 0.1),
                    max(1 + dd, 0.1)
                ]
                
                fig = go.Figure(data=go.Scatterpolar(
                    r=plot_values,
                    theta=categories,
                    fill='toself',
                    name=selected,
                    line_color='#00FFCC'
                ))
                fig.update_layout(
                    polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
                    showlegend=False,
                    template="plotly_dark"
                )
                st.plotly_chart(fig, use_container_width=True)
                
            with c_r:
                st.subheader("📋 股性行為統計 (2023~至今)")
                m1, m2 = st.columns(2)
                m1.metric("成功漲停次數", f"{int(hist['lu'] or 0)} 次")
                m2.metric("衝板失敗(炸板)", f"{int(hist['failed_lu'] or 0)} 次")
                
                st.markdown(f"""
                - **最新收盤價**：`{data['收盤']}`
                - **產業板塊**：`{sector_name}`
                - **20日年化波動率**：{vol*100:.2f}%
                - **漲停隔日溢價均值**：{(hist['ov'] or 0)*100:.2f}%
                - **漲停隔日最高點期望**：{(hist['nxt'] or 0)*100:.2f}%
                """)
                
                # 同業連結
                if not peers_df.empty:
                    st.write("**🔗 同產業聯動參考**：")
                    peer_links = [f"[{row['symbol']}]({current_url_base.replace('{s}', row['symbol'].split('.')[0])})" for _, row in peers_df.iterrows()]
                    st.caption(" ".join(peer_links))

            # --- 🚀 AI 診斷按鈕區塊 ---
            st.divider()
            if st.button("🚀 詢問 AI 專家對該股的深度判斷"):
                if "GEMINI_API_KEY" in st.secrets:
                    try:
                        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                        model = genai.GenerativeModel('gemini-1.5-flash')
                        
                        prompt = f"""
                        你是資深美股/台股交易員。請分析股票 {selected}：
                        數據如下：
                        - 2023至今漲停次數：{int(hist['lu'])} 次
                        - 2023至今炸板次數：{int(hist['failed_lu'])} 次
                        - 漲停隔日平均開盤獲利：{(hist['ov'] or 0)*100:.2f}%
                        - 20日波動率：{vol*100:.2f}%
                        - 最大回撤：{dd*100:.2f}%
                        
                        請針對「炸板率」與「隔日溢價」判斷該股是否適合隔日沖，並給予風控建議。
                        用 Markdown 格式回覆，並確保條列清晰。
                        """
                        
                        with st.spinner("AI 正在分析股性與籌碼壓力..."):
                            response = model.generate_content(prompt)
                            st.info("### 🤖 AI 專家診斷報告")
                            st.markdown(response.text)
                    except Exception as e:
                        st.error(f"AI 服務暫時不可用: {e}")
                else:
                    st.warning("請在 Secrets 中設定 GEMINI_API_KEY 以啟用 AI 功能。")
            
except Exception as e:
    st.error(f"系統異常: {e}")
