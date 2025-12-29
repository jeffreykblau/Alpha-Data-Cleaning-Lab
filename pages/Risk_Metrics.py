import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import google.generativeai as genai
import os

# 1. 頁面配置
st.set_page_config(page_title="風險指標深度掃描", layout="wide")

# 2. 超連結函數
def get_market_link(symbol, market):
    if market == "TW": return f"https://tw.stock.yahoo.com/quote/{symbol}"
    elif market == "US": return f"https://finviz.com/quote.ashx?t={symbol}"
    else: return f"https://www.tradingview.com/symbols/{symbol}"

# 3. 讀取資料庫
market_option = st.sidebar.selectbox("🚩 選擇市場", ("TW", "JP", "CN", "US", "HK", "KR"), key="risk_market")
db_map = {"TW":"tw_stock_warehouse.db", "JP":"jp_stock_warehouse.db", "CN":"cn_stock_warehouse.db", 
          "US":"us_stock_warehouse.db", "HK":"hk_stock_warehouse.db", "KR":"kr_stock_warehouse.db"}
target_db = db_map[market_option]

if not os.path.exists(target_db):
    st.error(f"請先回到主頁面同步 {market_option} 資料庫")
    st.stop()

conn = sqlite3.connect(target_db)

try:
    # 抓取風險相關欄位
    query = """
    SELECT StockID, 日期, 
           (SELECT name FROM stock_info WHERE symbol = StockID) as Name,
           (SELECT sector FROM stock_info WHERE symbol = StockID) as Sector,
           volatility_10d, volatility_20d, volatility_50d,
           drawdown_after_high_10d, drawdown_after_high_20d, drawdown_after_high_50d,
           recovery_from_dd_10d, [月累计漲跌幅(本月开盘)] as Ret_M
    FROM cleaned_daily_base
    WHERE 日期 = (SELECT MAX(日期) FROM cleaned_daily_base)
    """
    df = pd.read_sql(query, conn)
    
    st.title(f"🛡️ {market_option} 市場風險與穩定度分析")
    st.info("本頁面專注於『防禦性指標』，分析強勢股在拉回時的韌性。")

    # --- 區塊一：回撤與恢復力分布 ---
    st.subheader("📉 最大回撤分布 (Max Drawdown)")
    c1, c2, c3 = st.columns(3)
    
    with c1:
        fig1 = px.histogram(df, x='drawdown_after_high_10d', title="10D 回撤分布", color_discrete_sequence=['#ff4b4b'])
        st.plotly_chart(fig1, use_container_width=True)
    with c2:
        fig2 = px.histogram(df, x='drawdown_after_high_20d', title="20D 回撤分布", color_discrete_sequence=['#ff4b4b'])
        st.plotly_chart(fig2, use_container_width=True)
    with c3:
        # 散佈圖：分析『月漲幅』與『回撤』的關係
        fig3 = px.scatter(df, x='Ret_M', y='drawdown_after_high_20d', color='volatility_20d',
                         title="報酬 vs. 回撤 (顏色為波動率)", hover_name='Name')
        st.plotly_chart(fig3, use_container_width=True)

    # --- 區塊二：風險分箱排行榜 ---
    st.divider()
    col_l, col_r = st.columns(2)

    with col_l:
        st.subheader("🔥 高波動警戒區 (Volatility Top 20)")
        high_vol = df.sort_values('volatility_20d', ascending=False).head(20)
        st.dataframe(high_vol[['StockID', 'Name', 'volatility_20d', 'Ret_M']], use_container_width=True, hide_index=True)

    with col_r:
        st.subheader("🧱 抗跌韌性區 (Low Drawdown & Positive Return)")
        resilient = df[(df['Ret_M'] > 0.05) & (df['drawdown_after_high_20d'] > -0.05)].sort_values('Ret_M', ascending=False).head(20)
        st.dataframe(resilient[['StockID', 'Name', 'Ret_M', 'drawdown_after_high_20d']], use_container_width=True, hide_index=True)

    # --- 區塊三：行業風險分析 ---
    st.divider()
    st.subheader("🏘️ 行業平均波動與回撤")
    
    sector_risk = df.groupby('Sector')[['volatility_20d', 'drawdown_after_high_20d']].mean().reset_index()
    fig_sec = px.bar(sector_risk, x='Sector', y='volatility_20d', color='drawdown_after_high_20d',
                    title="各行業平均波動率 (顏色深淺代表平均回撤幅度)")
    st.plotly_chart(fig_sec, use_container_width=True)

    # --- 區塊四：AI 風險診斷 (新增雙按鈕功能) ---
    st.divider()
    st.subheader("🤖 市場風險 AI 診斷系統")
    st.markdown(f"""
    本模組會根據 **{market_option}** 市場的平均波動率、回撤深度與高風險行業進行分析。
    您可以選擇內建的 **Gemini 專家診斷**，或 **產生提問詞** 複製到 ChatGPT / Claude 進行交叉驗證。
    """)

    # 準備風險數據摘要
    avg_vol = df['volatility_20d'].mean()
    avg_dd = df['drawdown_after_high_20d'].mean()
    high_risk_sectors = sector_risk.sort_values('volatility_20d', ascending=False).head(3)['Sector'].tolist()
    
    risk_prompt = f"""你是一位資深風險管理專家。請分析 {market_option} 市場目前的風險指標：
當前市場數據摘要：
- 平均 20 日波動率：{avg_vol*100:.2f}%
- 平均 20 日最大回撤：{avg_dd*100:.2f}%
- 高波動風險行業：{", ".join(high_risk_sectors)}

請根據以上數據進行診斷：
1. 目前市場整體的穩定度如何？是否存在系統性風險拉回的跡象？
2. 針對高波動行業，投資者應如何設置保護性止損？
3. 從「抗跌韌性區」的表現來看，目前資金偏好哪種類型的避險標的？""".strip()

    # 按鈕佈局
    btn_col1, btn_col2 = st.columns(2)
    
    with btn_col1:
        run_ai = st.button(f"🚀 啟動 Gemini 風險診斷", use_container_width=True)
    
    with btn_col2:
        gen_prompt = st.button(f"📋 產生提問詞 (詢問其他 AI)", use_container_width=True)

    # 1. 處理內建 AI 診斷
    if run_ai:
        api_key = st.secrets.get("GEMINI_API_KEY")
        if not api_key:
            st.warning("⚠️ 請先在 Streamlit Secrets 中設定 GEMINI_API_KEY")
        else:
            try:
                genai.configure(api_key=api_key)
                all_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                target_model = next((m for m in ['models/gemini-1.5-flash', 'gemini-1.5-flash'] if m in all_models), all_models[0])
                model = genai.GenerativeModel(target_model)
                
                with st.spinner(f"AI 正在評估市場風險 (模型: {target_model})..."):
                    response = model.generate_content(risk_prompt)
                    st.info("### 🤖 市場風險 AI 診斷報告")
                    st.markdown(response.text)
            except Exception as e:
                st.error(f"AI 分析失敗: {e}")

    # 2. 處理提問詞顯示
    if gen_prompt:
        st.success("✅ 風險診斷提問詞已生成！")
        st.code(risk_prompt, language="text")
        st.info("""
        💡 **交叉驗證建議：**
        * **ChatGPT (OpenAI)**：擅長解讀波動率背後的市場心理與宏觀情緒。
        * **Claude (Anthropic)**：在風險規避策略與防守型資產配置的邏輯推演上非常嚴謹。
        * **對比點**：觀察不同模型對「高波動行業」的止損建議是否一致，若皆建議減碼，則應嚴格執行風控。
        """)

    # --- 區塊五：個股風險深度查詢 ---
    st.divider()
    st.subheader("🔍 個股風險深度查詢")
    selected = st.selectbox("選擇股票查看風險數據", options=(df['StockID'] + " " + df['Name']).tolist())
    if selected:
        sid = selected.split(" ")[0]
        st.write(f"已選取 {selected}，連結至：[外部分析圖表]({get_market_link(sid, market_option)})")
        risk_data = df[df['StockID'] == sid].iloc[0]
        st.write(f"該股當前 20D 波動率為 `{risk_data['volatility_20d']*100:.2f}%`，20D 最大回撤為 `{risk_data['drawdown_after_high_20d']*100:.2f}%`。")

except Exception as e:
    st.error(f"風險指標加載失敗: {e}")

finally:
    conn.close()

# --- 6. 底部快速連結 (Footer) ---
st.divider()
st.markdown("### 🔗 快速資源連結")
col_link1, col_link2, col_link3 = st.columns(3)
with col_link1:
    st.page_link("https://vocus.cc/article/694f813afd8978000101e75a", label="⚙️ 環境與 AI 設定教學", icon="🛠️")
with col_link2:
    st.page_link("https://vocus.cc/article/694f88bdfd89780001042d74", label="📖 儀表板功能詳解", icon="📊")
with col_link3:
    st.page_link("https://github.com/grissomlin/Alpha-Data-Cleaning-Lab", label="💻 GitHub 專案原始碼", icon="🐙")
