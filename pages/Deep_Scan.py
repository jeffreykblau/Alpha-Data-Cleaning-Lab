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

# 2. 市場與資料庫設定
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
    st.write("本模組整合 **動能、風險、隔日沖妖性、族群概念** 四大維度。")

    selected = st.selectbox("請搜尋代碼或名稱 (例如輸入 2330 或 信大)", options=stock_df['display'].tolist(), index=None)

    if selected:
        target_symbol = selected.split(" ")[0]
        conn = sqlite3.connect(target_db)
        
        # --- 數據抓取邏輯 (加入衝板失敗統計) ---
        scan_q = f"SELECT * FROM cleaned_daily_base WHERE StockID = '{target_symbol}' ORDER BY 日期 DESC LIMIT 1"
        data_all = pd.read_sql(scan_q, conn)
        
        hist_q = f"""
        SELECT COUNT(*) as t, SUM(is_limit_up) as lu, 
        SUM(CASE WHEN Prev_LU = 0 AND is_limit_up = 0 AND High_Alpha > 0.095 THEN 1 ELSE 0 END) as failed_lu,
        AVG(CASE WHEN Prev_LU=1 THEN Overnight_Alpha END) as ov,
        AVG(CASE WHEN Prev_LU=1 THEN Next_1D_Max END) as nxt
        FROM cleaned_daily_base WHERE StockID = '{target_symbol}'
        """
        hist = pd.read_sql(hist_q, conn).iloc[0]

        sample_q = f"SELECT Overnight_Alpha, Next_1D_Max FROM cleaned_daily_base WHERE StockID = '{target_symbol}' AND Prev_LU = 1"
        samples = pd.read_sql(sample_q, conn)
        
        temp_info_q = f"SELECT sector FROM stock_info WHERE symbol = '{target_symbol}'"
        sector_res = pd.read_sql(temp_info_q, conn)
        sector_name = sector_res.iloc[0,0] if not sector_res.empty else "未知"
        
        peer_q = f"SELECT symbol, name FROM stock_info WHERE sector = '{sector_name}' AND symbol != '{target_symbol}' LIMIT 12"
        peers_df = pd.read_sql(peer_q, conn)
        conn.close()

        if not data_all.empty:
            data = data_all.iloc[0]
            
            # --- 佈局一：雷達圖與核心指標 ---
            st.divider()
            col_left, col_right = st.columns([1, 1])
            
            with col_left:
                st.subheader("📊 多維度體質評分")
                r5 = data.get('Ret_5D', 0)
                r20 = data.get('Ret_20D', 0)
                r200 = data.get('Ret_200D', 0)
                vol = data.get('volatility_20d', 0)
                dd = data.get('drawdown_after_high_20d', 0)

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
                st.subheader("📋 當前行為指標")
                st.write(f"**最新收盤**：{data['收盤']}")
                st.write(f"**所屬產業**：{sector_name}")
                
                # 強調顯示漲停與炸板數據
                m1, m2 = st.columns(2)
                m1.metric("5年成功漲停", f"{int(hist['lu'] or 0)} 次")
                failed_count = int(hist['failed_lu'] or 0)
                m2.metric("衝板失敗(炸板)", f"{failed_count} 次", delta="需警惕" if failed_count > 5 else None, delta_color="inverse")

                st.write(f"**20D 波動率**：{vol*100:.2f}%")
                st.write(f"**平均開盤溢價**：{(hist['ov'] or 0)*100:.2f}%")
                st.write(f"**最高點期望值**：{(hist['nxt'] or 0)*100:.2f}%")

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
                st.subheader("🔗 同產業聯動 (點擊看圖)")
                if not peers_df.empty:
                    linked_peers = []
                    for _, row in peers_df.iterrows():
                        p_sym = row['symbol']
                        clean_id = p_sym.split('.')[0]
                        url = current_url_base.replace("{s}", clean_id)
                        linked_peers.append(f"• [{p_sym} {row['name']}]({url})")
                    st.markdown("\n".join(linked_peers))
                else:
                    st.write("暫無資料")

            # --- 佈局三：AI 專家報告 ---
            st.divider()
            if st.button("🚀 生成 AI 專家深度診斷報告"):
                if "GEMINI_API_KEY" in st.secrets:
                    try:
                        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                        model = genai.GenerativeModel('gemini-1.5-pro')
                        
                        prompt = f"""
                        你是投研專家。分析股票 {selected}：
                        - 產業：{sector_name}
                        - 5年漲停次數：{int(hist['lu'])}
                        - 衝板失敗(炸板)次數：{int(hist['failed_lu'])}
                        - 隔日溢價均值：{(hist['ov'] or 0)*100:.2f}%
                        
                        請針對「炸板次數」與「成功漲停次數」的比例，評價該標的的「股性」與「籌碼穩定度」，並給予交易建議。
                        """
                        
                        with st.spinner("AI 正在解析股性並生成報告..."):
                            response = model.generate_content(prompt)
                            raw_text = response.text

                            def make_stock_link(match):
                                symbol_full = match.group(0) 
                                symbol_num = match.group(1)  
                                link_url = current_url_base.replace("{s}", symbol_num)
                                return f"[{symbol_full}]({link_url})"

                            pattern = r"(\d{3,6})\.(?:TW|TWO|SS|SZ|T|HK|KS|N|O|Q)"
                            final_linked_text = re.sub(pattern, make_stock_link, raw_text)

                            st.info(f"### 🤖 AI 深度診斷：{selected}")
                            st.markdown(final_linked_text)
                    except Exception as e:
                        st.error(f"AI 分析失敗: {e}")
                else:
                    st.warning("請設定 GEMINI_API_KEY")

except Exception as e:
    st.error(f"系統異常: {e}")
