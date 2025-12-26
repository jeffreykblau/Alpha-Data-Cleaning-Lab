import streamlit as st
import sqlite3
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import google.generativeai as genai
import os
import re

# 1. 頁面配置
st.set_page_config(page_title="AI 綜合個股深度掃描", layout="wide")

# 2. 側邊欄與資料庫連線
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

# 定義各市場連結範本
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
    st.write("本模組整合 **動能、風險、隔日沖妖性、族群概念** 四大維度。")

    selected = st.selectbox("請搜尋代碼或名稱", options=stock_df['display'].tolist(), index=None)

    if selected:
        target_symbol = selected.split(" ")[0]
        conn = sqlite3.connect(target_db)
        
        # 抓取基礎數據
        scan_q = f"SELECT * FROM cleaned_daily_base WHERE StockID = '{target_symbol}' ORDER BY 日期 DESC LIMIT 1"
        data_all = pd.read_sql(scan_q, conn)
        
        hist_q = f"""
        SELECT COUNT(*) as t, SUM(is_limit_up) as lu, 
        AVG(CASE WHEN Prev_LU=1 THEN Overnight_Alpha END) as ov, 
        AVG(CASE WHEN Prev_LU=1 THEN Next_1D_Max END) as nxt 
        FROM cleaned_daily_base WHERE StockID = '{target_symbol}'
        """
        hist = pd.read_sql(hist_q, conn).iloc[0]
        
        sample_q = f"SELECT Overnight_Alpha, Next_1D_Max FROM cleaned_daily_base WHERE StockID = '{target_symbol}' AND Prev_LU = 1"
        samples = pd.read_sql(sample_q, conn)
        
        temp_info_q = f"SELECT sector FROM stock_info WHERE symbol = '{target_symbol}'"
        sector_name = pd.read_sql(temp_info_q, conn).iloc[0,0] if not pd.read_sql(temp_info_q, conn).empty else "未知"
        
        peer_q = f"SELECT symbol, name FROM stock_info WHERE sector = '{sector_name}' AND symbol != '{target_symbol}' LIMIT 12"
        peers_df = pd.read_sql(peer_q, conn)
        conn.close()

        if not data_all.empty:
            data = data_all.iloc[0]
            st.divider()
            
            # --- 佈局一：核心指標 ---
            c_l, c_r = st.columns(2)
            with c_l:
                st.subheader("📊 關鍵指標")
                st.write(f"**最新價格**：{data['收盤']}")
                st.write(f"**20D 波動**：{data.get('volatility_20d', 0)*100:.2f}%")
            
            with c_r:
                st.subheader("🔗 同產業聯動 (點擊看圖)")
                if not peers_df.empty:
                    linked_peers = []
                    for _, row in peers_df.iterrows():
                        p_sym = row['symbol']
                        clean_id = p_sym.split('.')[0]
                        url = current_url_base.replace("{s}", clean_id) # 安全替換
                        linked_peers.append(f"• [{p_sym} {row['name']}]({url})")
                    st.markdown("\n".join(linked_peers))
                else:
                    st.write("暫無資料")

            # --- 佈局三：AI 專家報告 (Python 強制連結邏輯) ---
            st.divider()
            if st.button("🚀 生成 AI 專家深度診斷報告"):
                if "GEMINI_API_KEY" in st.secrets:
                    try:
                        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                        model = genai.GenerativeModel('gemini-1.5-pro')
                        
                        prompt = f"""
                        你是股市專家，請針對股票 {selected} 進行深度分析。
                        1. **核心題材**：分析該股熱門概念。
                        2. **同概念股名單**：除資料庫標註的「{sector_name}」外，請根據市場邏輯列出 3-5 家相關標的。
                        3. **隔日沖數據參考**：5年內漲停{int(hist['lu'])}次，溢價期望值{(hist['ov'] or 0)*100:.2f}%。
                        """
                        
                        with st.spinner("AI 正在精煉數據並生成連結..."):
                            response = model.generate_content(prompt)
                            raw_text = response.text

                            # 🚀 健壯的 Regex 替換邏輯
                            def make_stock_link(match):
                                symbol_full = match.group(0) # 例如 2330.TW
                                symbol_num = match.group(1)  # 例如 2330
                                link_url = current_url_base.replace("{s}", symbol_num)
                                return f"[{symbol_full}]({link_url})"

                            # 支持多國後綴的 Regex
                            pattern = r"(\d{3,6})\.(?:TW|TWO|SS|SZ|T|HK|KS|N|O|Q)"
                            final_linked_text = re.sub(pattern, make_stock_link, raw_text)

                            st.info(f"### 🤖 AI 深度診斷：{selected}")
                            st.markdown(final_linked_text)
                            
                    except Exception as e:
                        st.error(f"AI 分析失敗: {e}")
                else:
                    st.warning("請先設定 GEMINI_API_KEY")

except Exception as e:
    st.error(f"系統異常: {e}")
