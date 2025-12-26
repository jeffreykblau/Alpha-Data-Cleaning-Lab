import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px

# 設定網頁標題
st.set_page_config(page_title="Alpha 六國漲停監控面板", layout="wide")
st.title("📊 全球股市漲停機率與行業分佈")

# 1. 側邊攔 - 市場切換
market_option = st.sidebar.selectbox(
    "選擇追蹤市場",
    ("TW", "JP", "CN", "US", "HK", "KR")
)

# 2. 資料庫連線 (假設你已將 .db 下載至同目錄或連結至 Drive)
def get_connection(market):
    db_map = {
        "TW": "tw_stock_warehouse.db",
        "JP": "jp_stock_warehouse.db",
        "CN": "cn_stock_warehouse.db",
        "US": "us_stock_warehouse.db",
        "HK": "hk_stock_warehouse.db",
        "KR": "kr_stock_warehouse.db"
    }
    return sqlite3.connect(db_map[market])

try:
    conn = get_connection(market_option)
    
    # 3. 讀取最近五天的數據 (JOIN 行業資訊)
    query = """
    SELECT p.日期, p.StockID, p.is_limit_up, i.sector as 行業
    FROM cleaned_daily_base p
    LEFT JOIN stock_info i ON p.StockID = i.symbol
    WHERE p.日期 >= (SELECT MAX(日期) FROM cleaned_daily_base) - 5
    """
    df = pd.read_sql(query, conn)
    df['日期'] = pd.to_datetime(df['日期']).dt.date
    
    # --- 統計核心邏輯 ---
    total_samples = len(df) # 母體：家數 * 天數
    lu_count = df['is_limit_up'].sum()
    lu_ratio = (lu_count / total_samples) * 100 if total_samples > 0 else 0
    
    # 4. 頂部看板指標
    col1, col2, col3 = st.columns(3)
    col1.metric("過去 5 日總樣本數 (家數*天)", f"{total_samples:,}")
    col2.metric("總漲停家數", f"{int(lu_count):,}")
    col3.metric("漲停佔比 (市場熱度)", f"{lu_ratio:.2f}%")

    # 5. 行業統計圖表
    st.subheader(f"🔥 {market_option} 市場：熱門漲停行業排行")
    
    # 僅篩選有漲停的資料進行行業統計
    df_lu = df[df['is_limit_up'] == 1]
    sector_stats = df_lu['行業'].value_counts().reset_index()
    sector_stats.columns = ['行業', '漲停個數']
    
    if not sector_stats.empty:
        fig = px.bar(sector_stats, x='漲停個數', y='行業', orientation='h',
                     title="各行業漲停家數統計", color='漲停個數',
                     color_continuous_scale='Reds')
        st.plotly_chart(fig, use_container_width=True)
        
        # 顯示詳細數據表格
        st.dataframe(sector_stats, hide_index=True, use_container_width=True)
    else:
        st.warning("過去五天該市場無漲停板紀錄。")

    conn.close()

except Exception as e:
    st.error(f"無法讀取資料庫：{e}")
    st.info("請確認 .db 檔案是否存在於正確路徑。")
