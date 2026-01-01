import streamlit as st
import sqlite3
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import google.genai as genai
import os
import urllib.parse

# 1. 頁面配置
st.set_page_config(page_title="AI 綜合個股深度掃描", layout="wide")

# 自訂樣式 (從您的參考程式碼整合)
st.markdown("""
    <style>
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; border: 1px solid #f0f2f6; box-shadow: 2px 2px 5px rgba(0,0,0,0.05); }
    .ai-section { background-color: #f8f9fa; padding: 20px; border-radius: 15px; border-left: 8px solid #28a745; box-shadow: 0 6px 20px rgba(0,0,0,0.12); }
    .password-protected { border: 2px solid #ff6b6b; border-radius: 8px; padding: 15px; background-color: #fff5f5; }
    </style>
""", unsafe_allow_html=True)

# 2. 市場資料庫配置與快取清除按鈕
market_option = st.sidebar.selectbox("🚩 選擇市場", ("TW", "JP", "CN", "US", "HK", "KR"), key="scan_market")

if st.sidebar.button("🧹 清除快取並強制更新"):
    st.cache_data.clear()
    st.rerun()

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

# 授權狀態初始化
if 'gemini_authorized' not in st.session_state:
    st.session_state.gemini_authorized = False

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
        
        # A. 抓取最新指標數據
        scan_q = f"SELECT * FROM cleaned_daily_base WHERE StockID = '{target_symbol}' ORDER BY 日期 DESC LIMIT 1"
        data_all = pd.read_sql(scan_q, conn)
        
        # B. 歷史股性統計 (2023 至今)
        hist_q = f"""
        SELECT COUNT(*) as t, SUM(is_limit_up) as lu, 
        SUM(CASE WHEN Prev_LU = 0 AND is_limit_up = 0 AND Ret_High > 0.095 THEN 1 ELSE 0 END) as failed_lu,
        AVG(CASE WHEN Prev_LU=1 THEN Overnight_Alpha END) as ov,
        AVG(CASE WHEN Prev_LU=1 THEN Next_1D_Max END) as nxt
        FROM cleaned_daily_base WHERE StockID = '{target_symbol}'
        """
        hist = pd.read_sql(hist_q, conn).iloc[0]

        # C. 獲取產業與同業
        temp_info_q = f"SELECT sector FROM stock_info WHERE symbol = '{target_symbol}'"
        sector_res = pd.read_sql(temp_info_q, conn)
        sector_name = sector_res.iloc[0,0] if not sector_res.empty else "未知"
        
        peer_q = f"SELECT symbol, name FROM stock_info WHERE sector = '{sector_name}' AND symbol != '{target_symbol}' LIMIT 8"
        peers_df = pd.read_sql(peer_q, conn)
        
        # 抓取最新日期用於報告
        latest_date = data_all['日期'].iloc[0] if not data_all.empty else "N/A"
        conn.close()

        if not data_all.empty:
            data = data_all.iloc[0]
            st.divider()
            
            col_radar, col_stats = st.columns(2)
            
            # --- 雷達圖 ---
            with col_radar:
                st.subheader("📊 多維度體質評分")
                r5 = data.get('Ret_5D', 0) or 0
                r20 = data.get('Ret_20D', 0) or 0
                r200 = data.get('Ret_200D', 0) or 0
                vol = data.get('volatility_20d', 0) or 0
                dd = data.get('drawdown_after_high_20d', 0) or 0

                categories = ['短線動能', '中線動能', '長線動能', '抗震穩定度', '防禦力']
                plot_values = [
                    min(max(r5 * 5 + 0.5, 0.1), 1),
                    min(max(r20 * 2 + 0.5, 0.1), 1),
                    min(max(r200 + 0.5, 0.1), 1),
                    max(1 - vol * 2, 0.1),
                    max(1 + dd, 0.1)
                ]
                
                fig = go.Figure(data=go.Scatterpolar(
                    r=plot_values, theta=categories, fill='toself', name=selected, line_color='#00d4ff'
                ))
                fig.update_layout(
                    polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
                    showlegend=False, template="plotly_dark"
                )
                st.plotly_chart(fig, use_container_width=True)
                
            # --- 行為統計 ---
            with col_stats:
                st.subheader("📋 股性統計 (2023~至今)")
                m1, m2 = st.columns(2)
                m1.metric("成功漲停次數", f"{int(hist['lu'] or 0)} 次")
                m2.metric("衝板失敗(炸板)", f"{int(hist['failed_lu'] or 0)} 次")
                
                st.write(f"**最新收盤價**：`{data['收盤']}`")
                st.write(f"**所屬產業**：`{sector_name}`")
                st.write(f"**漲停隔日溢價均值**：{(hist['ov'] or 0)*100:.2f}%")
                
                if not peers_df.empty:
                    st.write("**🔗 同產業參考**：")
                    links = [f"[{row['symbol']}]({current_url_base.replace('{s}', row['symbol'].split('.')[0])})" for _, row in peers_df.iterrows()]
                    st.caption(" ".join(links))

            # --- 🤖 AI 專家診斷系統 (整合四按鈕模式) ---
            st.divider()
            st.subheader(f"🤖 AI 專家診斷：{selected}")
            
            # 生成提示詞
            expert_prompt = f"""你是專業短線交易員。請深度分析股票 {selected}：
分析基準日：{latest_date}

## 數據指標 (2023 至今)
- 成功漲停次數：{int(hist['lu'] or 0)} 次
- 衝板失敗(炸板)次數：{int(hist['failed_lu'] or 0)} 次
- 漲停隔日溢價期望值：{(hist['ov'] or 0)*100:.2f}%
- 當前 20 日波動率：{vol*100:.2f}%
- 當前 20 日最大回撤：{dd*100:.2f}%
- 所屬產業：{sector_name}

## 分析任務
1. **籌碼與妖性**：結合「炸板率」與「波動率」分析該股籌碼壓力。
2. **隔日沖策略**：基於溢價期望值判斷是否適合隔日短進短出。
3. **風控建議**：給予具體的停損位建議與持倉風險提示。

請提供量化、具體且可執行的分析建議。"""

            # 顯示提示詞 (預設開啟，如需隱藏可改為 expanded=False)
            with st.expander("📋 查看完整AI分析提示詞", expanded=True):
                st.code(expert_prompt, language="text")
            
            # AI 平台按鈕佈局
            col_ai1, col_ai2, col_ai3, col_ai4 = st.columns(4)
            
            with col_ai1:
                # ChatGPT一鍵帶入
                encoded_prompt = urllib.parse.quote(expert_prompt)
                st.link_button(
                    "🔥 ChatGPT 分析",
                    f"https://chatgpt.com/?q={encoded_prompt}",
                    use_container_width=True,
                    help="自動在ChatGPT中打開此股票分析"
                )
            
            with col_ai2:
                st.link_button(
                    "🔍 DeepSeek 分析",
                    "https://chat.deepseek.com/",
                    use_container_width=True,
                    help="請複製上方提示詞貼到DeepSeek"
                )
            
            with col_ai3:
                st.link_button(
                    "📘 Claude 分析",
                    "https://claude.ai/",
                    use_container_width=True,
                    help="請複製上方提示詞貼到Claude"
                )
            
            with col_ai4:
                # Gemini 內建診斷 (密碼保護)
                if st.session_state.gemini_authorized:
                    if st.button("🤖 Gemini 分析", use_container_width=True, type="primary"):
                        api_key = st.secrets.get("GEMINI_API_KEY")
                        if not api_key:
                            st.warning("⚠️ 請先在 Streamlit Secrets 中設定 GEMINI_API_KEY")
                        else:
                            try:
                                genai.configure(api_key=api_key)
                                model = genai.GenerativeModel('gemini-1.5-flash')
                                with st.spinner("Gemini 正在分析中..."):
                                    response = model.generate_content(expert_prompt)
                                    if response:
                                        st.session_state.gemini_stock_report = response.text
                                        st.rerun()
                            except Exception as e:
                                st.error(f"AI 分析失敗: {e}")
                else:
                    st.markdown('<div class="password-protected">', unsafe_allow_html=True)
                    st.info("🔒 Gemini 需授權")
                    auth_pw = st.text_input("密碼：", type="password", key="stock_auth_pw")
                    if st.button("解鎖", key="stock_auth_btn"):
                        if auth_pw == st.secrets.get("AI_ASK_PASSWORD", "default_password"):
                            st.session_state.gemini_authorized = True
                            st.rerun()
                        else:
                            st.error("密碼錯誤")
                    st.markdown('</div>', unsafe_allow_html=True)

            # --- Gemini 報告顯示區塊 ---
            if 'gemini_stock_report' in st.session_state:
                st.divider()
                st.markdown(f"### 🤖 Gemini 專家診斷報告：{selected}")
                ai_res = st.session_state.gemini_stock_report
                
                # 使用 HTML 渲染精美報告框
                st.markdown(f"""
                    <div class="ai-section">
                        {ai_res.replace('\\n', '<br>')}
                    </div>
                """, unsafe_allow_html=True)

                report_md = f"# {selected} AI分析報告\n\n日期：{latest_date}\n\n{ai_res}"
                
                c1, c2 = st.columns(2)
                with c1:
                    st.download_button(
                        label="📥 下載報告 (.md)",
                        data=report_md.encode('utf-8'),
                        file_name=f"{target_symbol}_AI_Report.md",
                        mime="text/markdown",
                        use_container_width=True
                    )
                with c2:
                    if st.button("🗑️ 清除此報告", use_container_width=True):
                        del st.session_state.gemini_stock_report
                        st.rerun()

except Exception as e:
    st.error(f"系統異常: {e}")

# --- 底部快速連結 (Footer) ---
st.divider()
st.markdown("### 🔗 快速資源連結")
col_link1, col_link2, col_link3 = st.columns(3)
with col_link1:
    st.page_link("https://vocus.cc/article/694f813afd8978000101e75a", label="⚙️ 環境與 AI 設定教學", icon="🛠️")
with col_link2:
    st.page_link("https://vocus.cc/article/694f88bdfd89780001042d74", label="📖 儀表板功能詳解", icon="📊")
with col_link3:
    st.page_link("https://github.com/grissomlin/Alpha-Data-Cleaning-Lab", label="💻 GitHub 專案原始碼", icon="🐙")
