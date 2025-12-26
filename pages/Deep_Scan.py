import streamlit as st
import sqlite3
import pandas as pd
import plotly.graph_objects as go
import google.generativeai as genai
import os

# 1. 頁面配置
st.set_page_config(page_title="AI 深度個股掃描", layout="wide")

# 2. 側邊欄與資料庫連線
market_option = st.sidebar.selectbox("🚩 選擇市場", ("TW", "JP", "CN", "US", "HK", "KR"), key="scan_market")
db_map = {"TW":"tw_stock_warehouse.db", "JP":"jp_stock_warehouse.db", "CN":"cn_stock_warehouse.db", 
          "US":"us_stock_warehouse.db", "HK":"hk_stock_warehouse.db", "KR":"kr_stock_warehouse.db"}
target_db = db_map[market_option]

if not os.path.exists(target_db):
    st.error(f"請先回到主頁面同步 {market_option} 資料庫")
    st.stop()

# 3. 核心數據讀取
@st.cache_data
def get_full_stock_info(_db_path):
    conn = sqlite3.connect(_db_path)
    df = pd.read_sql("SELECT symbol, name, sector FROM stock_info", conn)
    conn.close()
    return df

try:
    stock_df = get_full_stock_info(target_db)
    stock_df['display'] = stock_df['symbol'] + " " + stock_df['name']
    
    st.title("🔍 AI 綜合個股深度掃描")
    st.write("本模組整合 **動能、風險、妖性** 三大維度，由 Gemini 提供深度分析。")

    selected = st.selectbox("請搜尋代碼或名稱", options=stock_df['display'].tolist(), index=None)

    if selected:
        target_symbol = selected.split(" ")[0]
        conn = sqlite3.connect(target_db)
        
        # 抓取該股所有關鍵維度 (最新一筆)
        scan_q = f"""
        SELECT * FROM cleaned_daily_base 
        WHERE StockID = '{target_symbol}' 
        ORDER BY 日期 DESC LIMIT 1
        """
        data = pd.read_sql(scan_q, conn).iloc[0]
        
        # 抓取歷史隔日沖統計 (五年)
        hist_q = f"""
        SELECT COUNT(*) as t, SUM(is_limit_up) as lu, 
        AVG(CASE WHEN Prev_LU=1 THEN Overnight_Alpha END) as ov,
        AVG(CASE WHEN Prev_LU=1 THEN Next_1D_Max END) as nxt
        FROM cleaned_daily_base WHERE StockID = '{target_symbol}'
        """
        hist = pd.read_sql(hist_q, conn).iloc[0]
        conn.close()

        # --- 佈局一：數據雷達圖 (視覺化動能與風險) ---
        st.divider()
        col_left, col_right = st.columns([1, 1])
        
        with col_left:
            st.subheader("📊 多維度評分")
            # 準備雷達圖數據
            categories = ['短線動能(5D)', '中線動能(20D)', '長線動能(200D)', '穩定度(1-波動)', '防禦力(1-回撤)']
            # 簡單正規化處理 (僅供視覺參考)
            values = [
                min(max(data['Ret_5D']*5 + 0.5, 0.1), 1),
                min(max(data['Ret_20D']*2 + 0.5, 0.1), 1),
                min(max(data['Ret_200D'] + 0.5, 0.1), 1),
                max(1 - data['volatility_20d']*2, 0.1),
                max(1 + data['drawdown_after_high_20d'], 0.1)
            ]
            
            fig = go.Figure(data=go.Scatterpolar(r=values, theta=categories, fill='toself', name=selected))
            fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 1])), showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

        with col_right:
            st.subheader("📋 核心指標清單")
            st.write(f"**行業分類**：{data.get('行業', '未知')}")
            st.write(f"**當前價格**：{data['收盤']}")
            st.write(f"**20D 波動率**：{data['volatility_20d']*100:.2f}%")
            st.write(f"**20D 最大回撤**：{data['drawdown_after_high_20d']*100:.2f}%")
            st.write(f"**歷史漲停次數**：{int(hist['lu'] or 0)} 次")
            st.write(f"**平均隔日溢價**：{(hist['ov'] or 0)*100:.2f}%")

        # --- 佈局二：Gemini AI 智慧診斷 ---
        st.divider()
        st.subheader("🤖 AI 投資診斷報告")
        
        if st.button("🚀 產生深度分析報告"):
            if "GEMINI_API_KEY" in st.secrets:
                try:
                    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                    model = genai.GenerativeModel('gemini-1.5-flash')
                    
                    analysis_prompt = f"""
                    你是一位專業的量化分析師。請針對股票 {selected} 給出深度評估報告：
                    【動能數據】
                    - 5D 報酬：{data['Ret_5D']*100:.2f}%
                    - 20D 報酬：{data['Ret_20D']*100:.2f}%
                    - 200D 報酬：{data['Ret_200D']*100:.2f}%
                    【風險數據】
                    - 波動率 (20D)：{data['volatility_20d']*100:.2f}%
                    - 最大回撤 (20D)：{data['drawdown_after_high_20d']*100:.2f}%
                    【妖性數據】
                    - 歷史漲停次數：{hist['lu']}
                    - 漲停後隔日平均溢價：{(hist['ov'] or 0)*100:.2f}%
                    
                    請從『動能持續性』、『回撤風險』、『個股慣性』三個面向分析，並給予 1-10 分的推薦分。
                    """
                    
                    with st.spinner("AI 正在解析大數據流..."):
                        response = model.generate_content(analysis_prompt)
                        st.markdown(response.text)
                except Exception as e:
                    st.error(f"AI 分析失敗: {e}")
            else:
                st.warning("請先設定 GEMINI_API_KEY")

except Exception as e:
    st.error(f"掃描模組載入失敗: {e}")
