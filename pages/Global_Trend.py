import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import os

# --- 1. 頁面配置 ---
st.set_page_config(page_title="全球強勢股產業連動監測", layout="wide")

st.title("🌎 全球強勢股產業連動監測")
st.caption("同步追蹤六大市場漲幅 > 10% 之個股，偵測全球產業資金流向")

# --- 2. 資料庫路徑與設定 ---
db_config = {
    "台灣 (TW)": "tw_stock_warehouse.db",
    "美國 (US)": "us_stock_warehouse.db",
    "中國 (CN)": "cn_stock_warehouse.db",
    "日本 (JP)": "jp_stock_warehouse.db",
    "香港 (HK)": "hk_stock_warehouse.db",
    "韓國 (KR)": "kr_stock_warehouse.db"
}

# 漲幅門檻設定
GAIN_THRESHOLD = 0.10

@st.cache_data(ttl=3600)
def fetch_global_strong_stocks():
    all_data = []
    
    for market_name, db_file in db_config.items():
        if not os.path.exists(db_file):
            continue
            
        conn = sqlite3.connect(db_file)
        try:
            # 獲取該國最新交易日
            latest_date = pd.read_sql("SELECT MAX(日期) FROM cleaned_daily_base", conn).iloc[0, 0]
            
            # 統一篩選條件：漲幅 >= 10% (不論是否鎖漲停)
            # 台灣包含上市櫃、興櫃大於10%的股票
            query = f"""
            SELECT p.StockID, i.name as Name, i.sector as Sector, p.Ret_Day, p.收盤
            FROM cleaned_daily_base p
            LEFT JOIN stock_info i ON p.StockID = i.symbol
            WHERE p.日期 = '{latest_date}' AND p.Ret_Day >= {GAIN_THRESHOLD}
            """
            df = pd.read_sql(query, conn)
            df['Market'] = market_name
            df['Date'] = latest_date
            all_data.append(df)
        except Exception as e:
            st.warning(f"{market_name} 讀取失敗: {e}")
        finally:
            conn.close()
            
    return pd.concat(all_data, ignore_index=True) if all_data else pd.DataFrame()

# --- 3. 執行數據抓取 ---
global_df = fetch_global_strong_stocks()

if global_df.empty:
    st.error("❌ 暫無數據，請確保資料庫已同步且包含最新交易日數據。")
else:
    # 處理香港與未分類產業
    global_df['Sector'] = global_df['Sector'].fillna('未分類/其他')

    # --- 數據儀表板 ---
    col_l, col_r = st.columns([1, 1])

    with col_l:
        st.subheader("📊 全球強勢產業熱點")
        # 統計各產業在各國出現的次數
        sector_market_count = global_df.groupby(['Sector', 'Market']).size().reset_index(name='Count')
        
        fig = px.bar(
            sector_market_count, 
            x='Count', y='Sector', color='Market',
            orientation='h', title="跨國強勢個股產業分佈",
            color_discrete_sequence=px.colors.qualitative.Pastel
        )
        fig.update_layout(yaxis={'categoryorder':'total ascending'}, height=600)
        st.plotly_chart(fig, use_container_width=True)

    with col_r:
        st.subheader("🔍 強勢個股清單")
        # 讓使用者篩選市場
        selected_markets = st.multiselect("篩選顯示國家", options=list(db_config.keys()), default=list(db_config.keys()))
        display_df = global_df[global_df['Market'].isin(selected_markets)].sort_values(by='Ret_Day', ascending=False)
        
        st.dataframe(
            display_df[['Market', 'StockID', 'Name', 'Sector', 'Ret_Day']],
            column_config={
                "Ret_Day": st.column_config.NumberColumn("漲幅", format="%.2f%%")
            },
            hide_index=True, use_container_width=True
        )

    # --- 4. 趨勢分析總結 ---
    st.divider()
    st.subheader("💡 跨國趨勢觀察 (AI 分析建議)")
    
    # 找出在多個國家同時出現的產業
    sector_summary = global_df.groupby('Sector')['Market'].nunique().sort_values(ascending=False)
    hot_sectors = sector_summary[sector_summary >= 2].index.tolist()
    
    if hot_sectors:
        st.success(f"🔥 **偵測到跨國共振產業：** {', '.join(hot_sectors)}")
        st.write("這些產業在至少兩個國家同時出現漲幅 > 10% 的強勢股，暗示全球資金可能正集結於此。")
    else:
        st.info("目前資金分佈較為分散，尚未觀察到顯著的跨國產業共振。")

    # --- 5. AI 專家解讀 (串接 Gemini) ---
    if st.button("🤖 啟動全球趨勢 AI 診斷"):
        api_key = st.secrets.get("GEMINI_API_KEY")
        if api_key:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            # 自動偵測模型邏輯
            all_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            target_model = 'models/gemini-1.5-flash' if 'models/gemini-1.5-flash' in all_models else all_models[0]
            model = genai.GenerativeModel(target_model)
            
            # 準備數據摘要給 AI
            summary_text = global_df.groupby(['Market', 'Sector']).size().to_string()
            
            prompt = f"""
            你是一位全球宏觀策略分析師。以下是今日全球六大市場漲幅超過 10% 的強勢股產業分佈：
            {summary_text}
            
            請根據以上數據回答：
            1. 是否存在某個產業在多個國家（如台、美、日）同時爆發？
            2. 這種現象背後的全球性題材可能是什麼？
            3. 投資者應該注意哪些風險？
            請用繁體中文回覆，Markdown 呈現。
            """
            
            with st.spinner("AI 正在比對全球宏觀趨勢..."):
                response = model.generate_content(prompt)
                st.markdown(response.text)
