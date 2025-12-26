import streamlit as st
import sqlite3
import pandas as pd
import plotly.graph_objects as go
import google.generativeai as genai
import os

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

if not os.path.exists(target_db):
    st.error(f"請先回到首頁同步 {market_option} 數據庫")
    st.stop()

# 3. 核心數據讀取
@st.cache_data
def get_full_stock_info(_db_path):
    conn = sqlite3.connect(_db_path)
    # 嘗試抓取股票清單，若表不存在則回傳空表
    try:
        df = pd.read_sql("SELECT symbol, name FROM stock_info", conn)
    except:
        df = pd.DataFrame(columns=['symbol', 'name'])
    conn.close()
    return df

try:
    stock_df = get_full_stock_info(target_db)
    stock_df['display'] = stock_df['symbol'] + " " + stock_df['name']
    
    st.title("🔍 AI 綜合個股深度掃描")
    st.write("本模組整合 **動能、風險、妖性** 三大維度，由 Gemini 提供深度分析。")

    selected = st.selectbox("請搜尋代碼或名稱 (例如輸入 1101 或 台泥)", options=stock_df['display'].tolist(), index=None)

    if selected:
        target_symbol = selected.split(" ")[0]
        conn = sqlite3.connect(target_db)
        
        # 抓取該股最新一筆所有資料
        scan_q = f"SELECT * FROM cleaned_daily_base WHERE StockID = '{target_symbol}' ORDER BY 日期 DESC LIMIT 1"
        data_all = pd.read_sql(scan_q, conn)
        
        # 抓取歷史隔日沖統計 (五年)
        hist_q = f"""
        SELECT COUNT(*) as t, SUM(is_limit_up) as lu, 
        AVG(CASE WHEN Prev_LU=1 THEN Overnight_Alpha END) as ov,
        AVG(CASE WHEN Prev_LU=1 THEN Next_1D_Max END) as nxt
        FROM cleaned_daily_base WHERE StockID = '{target_symbol}'
        """
        hist = pd.read_sql(hist_q, conn).iloc[0]
        conn.close()

        if not data_all.empty:
            data = data_all.iloc[0]
            cols = data.index.tolist()

            # --- 動態欄位偵測工具 ---
            def get_val(names):
                for n in names:
                    if n in cols: return data[n]
                return 0

            # 抓取雷達圖與 AI 分析所需的關鍵數據
            r5 = get_val(['Ret_5D', 'Ret_5d', '5日漲跌幅', 'rolling_ret_5'])
            r20 = get_val(['Ret_20D', 'Ret_20d', '20日漲跌幅', 'rolling_ret_20'])
            r200 = get_val(['Ret_200D', 'Ret_200d', '200日漲跌幅', 'rolling_ret_200'])
            vol = get_val(['volatility_20d', 'vol_20', '20日波動率'])
            dd = get_val(['drawdown_after_high_20d', 'dd_20', '20日回撤'])
            curr_price = get_val(['收盤', 'Close', 'price'])

            # --- 佈局一：雷達圖 ---
            st.divider()
            col_left, col_right = st.columns([1, 1])
            
            with col_left:
                st.subheader("📊 多維度體質評分")
                categories = ['短線動能', '中線動能', '長線動能', '穩定度', '防禦力']
                # 正規化數值以便繪圖 (0-1 區間)
                plot_values = [
                    min(max(r5 * 5 + 0.5, 0.1), 1),
                    min(max(r20 * 2 + 0.5, 0.1), 1),
                    min(max(r200 + 0.5, 0.1), 1),
                    max(1 - vol * 2, 0.1),
                    max(1 + dd, 0.1)
                ]
                
                fig = go.Figure(data=go.Scatterpolar(r=plot_values, theta=categories, fill='toself', name=selected))
                fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 1])), showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

            with col_right:
                st.subheader("📋 當前核心指標")
                st.write(f"**最新日期**：{data['日期']}")
                st.write(f"**收盤價**：{curr_price}")
                st.write(f"**20D 波動率**：{vol*100:.2f}%")
                st.write(f"**20D 最大回撤**：{dd*100:.2f}%")
                st.write(f"**5年漲停次數**：{int(hist['lu'] or 0)} 次")
                st.write(f"**平均隔日溢價**：{(hist['ov'] or 0)*100:.2f}%")

            # --- 佈局二：AI 深度報告 ---
            st.divider()
            if st.button("🚀 生成 AI 深度診斷報告"):
                if "GEMINI_API_KEY" in st.secrets:
                    try:
                        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                        # 自動偵測可用模型
                        available = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                        target_model = 'models/gemini-1.5-flash' if 'models/gemini-1.5-flash' in available else available[0]
                        model = genai.GenerativeModel(target_model)
                        
                        prompt = f"""
                        你是一位專業量化分析師，請分析股票 {selected}：
                        - 短/中/長線動能：{r5*100:.1f}% / {r20*100:.1f}% / {r200*100:.1f}%
                        - 20D波動率：{vol*100:.1f}%, 20D最大回撤：{dd*100:.1f}%
                        - 歷史妖性：漲停{hist['lu']}次，隔日開盤溢價{(hist['ov'] or 0)*100:.2f}%
                        請給出投資建議，評估其是否適合隔日沖或波段持有。
                        """
                        
                        with st.spinner(f"AI 正在精煉數據 (使用 {target_model})..."):
                            response = model.generate_content(prompt)
                            st.markdown(f"### 🤖 AI 診斷結果\n{response.text}")
                    except Exception as e:
                        st.error(f"AI 分析失敗: {e}")
                else:
                    st.warning("請在 Secrets 中設定 GEMINI_API_KEY")

except Exception as e:
    st.error(f"掃描模組載入失敗: {e}")
