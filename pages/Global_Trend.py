import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import os
import io
import json
import urllib.parse
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.service_account import Credentials
import google.genai as genai

# --- 1. 頁面配置 ---
st.set_page_config(page_title="全球強勢股產業連動監測", layout="wide")

st.title("🌎 全球強勢股產業連動監測")
st.caption("同步追蹤六大市場漲幅 > 10% 之個股，偵測全球產業資金流向")

# 自訂樣式
st.markdown("""
    <style>
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; border: 1px solid #f0f2f6; box-shadow: 2px 2px 5px rgba(0,0,0,0.05); }
    .ai-section { background-color: #f8f9fa; padding: 20px; border-radius: 15px; border-left: 8px solid #28a745; box-shadow: 0 6px 20px rgba(0,0,0,0.12); }
    .password-protected { border: 2px solid #ff6b6b; border-radius: 8px; padding: 15px; background-color: #fff5f5; }
    </style>
""", unsafe_allow_html=True)

# --- 2. 市場與資料庫設定 ---
db_config = {
#    "TW": "tw_stock_warehouse.db",
#    "US": "us_stock_warehouse.db",
 #   "CN": "cn_stock_warehouse.db",
#    "JP": "jp_stock_warehouse.db",
    "HK": "hk_stock_warehouse.db",
#    "KR": "kr_stock_warehouse.db"
}

# 授權狀態初始化
if 'gemini_authorized' not in st.session_state:
    st.session_state.gemini_authorized = False

# --- 3. 自動下載邏輯 ---
def download_missing_dbs():
    creds_json = st.secrets.get("GDRIVE_SERVICE_ACCOUNT")
    if not creds_json:
        st.error("❌ 找不到 Google Drive 憑證 (GDRIVE_SERVICE_ACCOUNT)")
        return
    
    try:
        creds = Credentials.from_service_account_info(json.loads(creds_json))
        service = build('drive', 'v3', credentials=creds)
        
        for m_abbr, db_file in db_config.items():
            if not os.path.exists(db_file):
                with st.spinner(f"📥 正在從雲端同步 {m_abbr} 資料庫..."):
                    query = f"name = '{db_file}' and trashed = false"
                    results = service.files().list(q=query, fields="files(id, name)").execute()
                    files = results.get('files', [])
                    if files:
                        file_id = files[0]['id']
                        request = service.files().get_media(fileId=file_id)
                        fh = io.FileIO(db_file, 'wb')
                        downloader = MediaIoBaseDownload(fh, request)
                        done = False
                        while not done:
                            status, done = downloader.next_chunk()
                        st.sidebar.success(f"✅ {m_abbr} 同步成功")
                    else:
                        st.sidebar.warning(f"⚠️ 雲端找不到 {db_file}")
    except Exception as e:
        st.error(f"下載失敗: {e}")

# --- 側邊欄控制 ---
with st.sidebar:
    st.header("⚙️ 數據管理")
    if st.button("🚀 一鍵同步六國資料庫"):
        st.info("開始同步資料庫，請稍候...")
        download_missing_dbs()
        st.cache_data.clear()
        st.rerun()
    
    st.divider()
    
    # 授權設定
    st.subheader("🔐 AI 授權設定")
    if not st.session_state.gemini_authorized:
        password_input = st.text_input("授權密碼：", type="password", key="sidebar_pw")
        if st.button("🔓 授權解鎖", use_container_width=True):
            if password_input == st.secrets.get("AI_ASK_PASSWORD", "default_password"):
                st.session_state.gemini_authorized = True
                st.rerun()
            else:
                st.error("❌ 密碼錯誤")
    else:
        st.success("✅ Gemini 已授權")
        if st.button("🔒 撤銷授權"):
            st.session_state.gemini_authorized = False
            st.rerun()

    st.divider()
    st.write("📁 本地檔案狀態：")
    available_markets = []
    for m_abbr, db_file in db_config.items():
        ready = os.path.exists(db_file)
        st.write(f"{'🟢' if ready else '🔴'} {m_abbr}")
        if ready: available_markets.append(m_abbr)

# --- 4. 數據抓取邏輯 ---
@st.cache_data(ttl=600)
def fetch_global_strong_stocks(markets):
    all_list = []
    for m in markets:
        db = db_config[m]
        conn = sqlite3.connect(db)
        try:
            latest = pd.read_sql("SELECT MAX(日期) FROM cleaned_daily_base", conn).iloc[0,0]
            query = f"""
            SELECT p.StockID, i.name as Name, i.sector as Sector, p.Ret_Day
            FROM cleaned_daily_base p
            LEFT JOIN stock_info i ON p.StockID = i.symbol
            WHERE p.日期 = '{latest}' AND p.Ret_Day >= 0.1
            """
            df = pd.read_sql(query, conn)
            df['Market'] = m
            all_list.append(df)
        except:
            pass
        finally:
            conn.close()
    return pd.concat(all_list, ignore_index=True) if all_list else pd.DataFrame()

# --- 5. 視覺化與分析 ---
if available_markets:
    global_df = fetch_global_strong_stocks(available_markets)
    
    if not global_df.empty:
        global_df['Sector'] = global_df['Sector'].fillna('未分類/香港/興櫃')

        col_l, col_r = st.columns([1.2, 1])
        
        with col_l:
            st.subheader("📊 跨國強勢產業熱點")
            chart_df = global_df.groupby(['Sector', 'Market']).size().reset_index(name='Count')
            fig = px.bar(
                chart_df, x='Count', y='Sector', color='Market', orientation='h',
                title="全球強勢個股產業分佈 (漲幅 > 10%)", barmode='stack',
                color_discrete_map={"TW": "#FF4B4B", "US": "#1C83E1", "CN": "#E11C1C", "JP": "#FFFFFF", "HK": "#FFD700", "KR": "#00FFCC"}
            )
            fig.update_layout(yaxis={'categoryorder':'total ascending'}, template="plotly_dark")
            st.plotly_chart(fig, use_container_width=True)

        with col_r:
            st.subheader("🔍 今日全球強勢榜")
            st.dataframe(
                global_df.sort_values(['Market', 'Ret_Day'], ascending=[True, False]),
                column_config={"Ret_Day": st.column_config.NumberColumn("漲幅", format="%.2f%%")},
                use_container_width=True, hide_index=True
            )

        # --- AI 趨勢分析區塊 (升級版) ---
        st.divider()
        st.subheader("🤖 全球產業趨勢 AI 專家診斷")
        st.markdown("""
        本模組分析今日全球市場資金流向。您可以直接展開提示詞查看數據，或使用一鍵按鈕將指令帶入各 AI 平台。
        """)

        # 預先準備 AI 提問詞內容
        sector_summary = global_df.groupby(['Sector', 'Market']).size().to_string()
        trend_prompt = f"""你是一位宏觀投資專家，請分析今日全球漲幅超過10%的股票分佈數據：

{sector_summary}

## 分析任務：
1. **產業跨國聯動**：哪些產業出現跨國聯動現象？（例如：美、台、日同步大漲 AI 半導體）
2. **全球趨勢解讀**：這些現象背後的驅動力為何？（政策推動、技術突破或資金避險）
3. **投資佈局建議**：給予宏觀角度的風險評估與後續佈局策略。

請提供專業、具備前瞻性的分析建議。"""

        # 顯示提示詞 (預設展開)
        with st.expander("📋 查看完整全球趨勢 AI 分析提示詞", expanded=True):
            st.code(trend_prompt.strip(), language="text")

        # 四按鈕佈局
        col_ai1, col_ai2, col_ai3, col_ai4 = st.columns(4)
        
        with col_ai1:
            # ChatGPT 一鍵帶入
            encoded_prompt = urllib.parse.quote(trend_prompt.strip())
            st.link_button(
                "🔥 ChatGPT 分析",
                f"https://chatgpt.com/?q={encoded_prompt}",
                use_container_width=True,
                help="自動在 ChatGPT 中開啟全球趨勢分析"
            )
        
        with col_ai2:
            st.link_button(
                "🔍 DeepSeek 分析",
                "https://chat.deepseek.com/",
                use_container_width=True,
                help="手動複製上方提示詞貼到 DeepSeek"
            )
        
        with col_ai3:
            st.link_button(
                "📘 Claude 分析",
                "https://claude.ai/",
                use_container_width=True,
                help="手動複製上方提示詞貼到 Claude"
            )
        
        with col_ai4:
            # Gemini 內建診斷 (密碼保護)
            if st.session_state.gemini_authorized:
                if st.button("🚀 Gemini 診斷", use_container_width=True, type="primary"):
                    api_key = st.secrets.get("GEMINI_API_KEY")
                    if not api_key:
                        st.warning("⚠️ 請先設定 GEMINI_API_KEY")
                    else:
                        try:
                            genai.configure(api_key=api_key)
                            model = genai.GenerativeModel('gemini-1.5-flash')
                            with st.spinner("Gemini 正在解析全球趨勢..."):
                                response = model.generate_content(trend_prompt)
                                st.session_state.global_trend_report = response.text
                                st.rerun()
                        except Exception as e:
                            st.error(f"AI 分析失敗: {e}")
            else:
                # 未授權顯示解鎖提示
                st.markdown('<div class="password-protected">', unsafe_allow_html=True)
                st.caption("🔒 Gemini 需授權")
                auth_pw = st.text_input("密碼：", type="password", key="global_auth_pw", label_visibility="collapsed")
                if st.button("解鎖並分析", key="global_auth_btn"):
                    if auth_pw == st.secrets.get("AI_ASK_PASSWORD", "default_password"):
                        st.session_state.gemini_authorized = True
                        st.rerun()
                    else:
                        st.error("密碼錯誤")
                st.markdown('</div>', unsafe_allow_html=True)

        # 顯示 Gemini 報告
        if 'global_trend_report' in st.session_state:
            st.divider()
            st.markdown("### 🤖 Gemini 全球趨勢分析報告")
            
            st.markdown(f"""
                <div class="ai-section">
                    {st.session_state.global_trend_report.replace('\\n', '<br>')}
                </div>
            """, unsafe_allow_html=True)
            
            c_dl, c_cl = st.columns(2)
            with c_dl:
                st.download_button(
                    label="📥 下載趨勢報告 (.md)",
                    data=st.session_state.global_trend_report.encode('utf-8'),
                    file_name="Global_Trend_Report.md",
                    mime="text/markdown",
                    use_container_width=True
                )
            with c_cl:
                if st.button("🗑️ 清除報告", use_container_width=True):
                    del st.session_state.global_trend_report
                    st.rerun()

    else:
        st.warning("今日各國暫無漲幅 > 10% 的股票數據。")
else:
    st.error("請在側邊欄點擊「一鍵同步六國資料庫」以載入數據。")

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
