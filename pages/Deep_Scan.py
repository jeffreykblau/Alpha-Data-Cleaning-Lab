import streamlit as st
import sqlite3
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
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

# 3. 核心數據讀取
@st.cache_data
def get_full_stock_info(_db_path):
    conn = sqlite3.connect(_db_path)
    try:
        # 增加讀取 sector 欄位以利後續使用
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

    selected = st.selectbox("請搜尋代碼或名稱 (例如輸入 2330 或 台積電)", options=stock_df['display'].tolist(), index=None)

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

        # 抓取隔日沖樣本數據
        sample_q = f"SELECT Overnight_Alpha, Next_1D_Max FROM cleaned_daily_base WHERE StockID = '{target_symbol}' AND Prev_LU = 1"
        samples = pd.read_sql(sample_q, conn)
        
        # 獲取同產業公司名單
        temp_info_q = f"SELECT sector FROM stock_info WHERE symbol = '{target_symbol}'"
        sector_res = pd.read_sql(temp_info_q, conn)
        sector_name = sector_res.iloc[0,0] if not sector_res.empty else "未知"
        
        peer_q = f"SELECT symbol, name FROM stock_info WHERE sector = '{sector_name}' AND symbol != '{target_symbol}' LIMIT 12"
        peers_df = pd.read_sql(peer_q, conn)
        
        conn.close()

        if not data_all.empty:
            data = data_all.iloc[0]
            
            # 取得顯示指標
            r5 = data.get('Ret_5D', 0)
            r20 = data.get('Ret_20D', 0)
            r200 = data.get('Ret_200D', 0)
            vol = data.get('volatility_20d', 0)
            dd = data.get('drawdown_after_high_20d', 0)
            curr_price = data.get('收盤', 0)

            # --- 佈局一：雷達圖與核心指標 ---
            st.divider()
            col_left, col_right = st.columns([1, 1])
            
            with col_left:
                st.subheader("📊 多維度體質評分")
                categories = ['短線動能', '中線動能', '長線動能', '穩定度', '防禦力']
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
                st.subheader("📋 當前關鍵指標")
                st.write(f"**最新日期**：{data['日期']}")
                st.write(f"**收盤價格**：{curr_price}")
                st.write(f"**所屬產業**：{sector_name}")
                st.write(f"**20D 波動率**：{vol*100:.2f}%")
                st.write(f"**5年漲停次數**：{int(hist['lu'] or 0)} 次")
                st.write(f"**平均溢價期望**：{(hist['ov'] or 0)*100:.2f}%")

            # --- 佈局二：⚡ 隔日沖與族群聯動 ---
            st.divider()
            c1, c2 = st.columns([2, 1])
            
            with c1:
                st.subheader("⚡ 隔日沖慣性分布")
                if not samples.empty:
                    fig_hist = px.histogram(
                        samples, x=samples['Overnight_Alpha']*100, 
                        nbins=15, title="漲停後隔日開盤利潤分布 (%)",
                        labels={'x': '利潤 %', 'count': '次數'},
                        color_discrete_sequence=['#FFD700']
                    )
                    st.plotly_chart(fig_hist, use_container_width=True)
                else:
                    st.info("該股五年內無漲停紀錄。")

            with c2:
                st.subheader("🔗 同產業聯動 (點擊跳轉圖表)")
                if not peers_df.empty:
                    # 生成帶超連結的 Markdown 字串
                    linked_peers = []
                    for _, row in peers_df.iterrows():
                        p_sym = row['symbol']
                        p_name = row['name']
                        # 處理台灣代號後綴 (2330.TW -> 2330)
                        clean_id = p_sym.split('.')[0]
                        url = current_url_base.format(s=clean_id)
                        linked_peers.append(f"• [{p_sym} {p_name}]({url})")
                    
                    # 顯示兩排顯示，增加易讀性
                    st.markdown("\n".join(linked_peers))
                else:
                    st.write("暫無相關產業資料")

            # --- 佈局三：AI 專家報告 ---
            st.divider()
            if st.button("🚀 生成 AI 專家深度診斷報告 (含同概念股名單)"):
                if "GEMINI_API_KEY" in st.secrets:
                    try:
                        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                        target_model = next((c for c in ['models/gemini-1.5-flash', 'gemini-1.5-flash', 'models/gemini-pro'] if c in available_models), available_models[0])
                        model = genai.GenerativeModel(target_model)
                        
                        # 在指令中要求 AI 也要輸出超連結格式
                        prompt = f"""
                        你是一位資深的股市投研專家。請針對股票 {selected} 進行深度分析：
                        1. **核心題材與概念**：這檔股票目前市場熱門題材是什麼？
                        2. **同概念股名單**：除了「{sector_name}」，請根據市場邏輯列出 3-5 家具備相同題材的公司。
                        
                        🚨 **超連結強制指令** 🚨
                        分析中提到的所有公司名與代號，請務必轉換為 Markdown 連結。
                        範例：[2330 台積電]({current_url_base.format(s='2330')})
                        連結範本為：{current_url_base} (請將 {{s}} 替換為該股純數字代號)

                        3. **隔日沖與投資建議**：
                           - 歷史漲停次數：{int(hist['lu'] or 0)}
                           - 隔日溢價均值：{(hist['ov'] or 0)*100:.2f}%
                        請給出具體判斷。
                        """
                        
                        with st.spinner(f"AI 正在掃描題材並自動配置連結..."):
                            response = model.generate_content(prompt)
                            st.info(f"### 🤖 AI 深度診斷：{selected}")
                            # st.markdown 會自動渲染 AI 回傳的連結
                            st.markdown(response.text)
                    except Exception as e:
                        st.error(f"AI 分析失敗: {e}")
                else:
                    st.warning("請先在 .streamlit/secrets.toml 中設定 GEMINI_API_KEY")

except Exception as e:
    st.error(f"模組執行異常: {e}")
