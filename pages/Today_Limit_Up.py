import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import google.generativeai as genai
import os
import urllib.parse

# --- 1. 頁面配置與樣式 ---
st.set_page_config(page_title="全球漲停板 AI 分析儀 2.0", layout="wide")

# 自訂CSS樣式
st.markdown("""
    <style>
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; border: 1px solid #f0f2f6; box-shadow: 2px 2px 5px rgba(0,0,0,0.05); }
    .industry-header { background-color: #f8f9fa; padding: 10px; border-radius: 5px; margin: 10px 0; }
    .ai-section { background-color: #fff3cd; padding: 15px; border-radius: 8px; border-left: 5px solid #ffc107; }
    </style>
""", unsafe_allow_html=True)

# --- 2. 市場資料庫配置 ---
st.sidebar.header("⚙️ 市場設定")
market_option = st.sidebar.selectbox("🚩 選擇分析市場", ("TW", "JP", "CN", "US", "HK", "KR"), key="today_market")

st.sidebar.header("🔐 AI 設定")
# 密碼保護機制
if 'gemini_authorized' not in st.session_state:
    st.session_state.gemini_authorized = False

# 只有未授權時才顯示密碼輸入
if not st.session_state.gemini_authorized:
    with st.sidebar.expander("🔒 Gemini API 授權", expanded=True):
        password_input = st.text_input("授權密碼：", type="password", key="gemini_pw")
        if st.button("🔓 授權解鎖", use_container_width=True):
            if password_input == st.secrets.get("AI_ASK_PASSWORD", "default_password"):
                st.session_state.gemini_authorized = True
                st.rerun()
            else:
                st.error("❌ 密碼錯誤")
        st.caption("💡 授權後在同次會話中有效，關閉瀏覽器後需重新授權")
else:
    st.sidebar.success("✅ Gemini API 已授權")

db_map = {
    "TW": "tw_stock_warehouse.db", 
    "JP": "jp_stock_warehouse.db", 
    "CN": "cn_stock_warehouse.db", 
    "US": "us_stock_warehouse.db", 
    "HK": "hk_stock_warehouse.db", 
    "KR": "kr_stock_warehouse.db"
}

# 外部圖表連結模板
url_templates = {
    "TW": "https://www.wantgoo.com/stock/{s}/technical-chart",
    "US": "https://www.tradingview.com/symbols/{s}/",
    "JP": "https://jp.tradingview.com/symbols/TSE-{s}/",
    "CN": "https://panyi.eastmoney.com/pc_sc_kline.html?s={s}",
    "HK": "https://www.tradingview.com/symbols/HKEX-{s}/",
    "KR": "https://www.tradingview.com/symbols/KRX-{s}/"
}
current_url_base = url_templates.get(market_option, "https://google.com/search?q={s}")
target_db = db_map[market_option]

if not os.path.exists(target_db):
    st.error(f"❌ 找不到 {market_option} 資料庫檔案。")
    st.stop()

conn = sqlite3.connect(target_db)

try:
    # A. 獲取最新交易日
    latest_date = pd.read_sql("SELECT MAX(日期) FROM cleaned_daily_base", conn).iloc[0, 0]
    
    # B. 抓取當日漲停股票數據
    query_today = f"""
    SELECT p.StockID, i.name as Name, i.sector as Sector, p.收盤, p.Ret_Day, p.Seq_LU_Count, p.is_limit_up
    FROM cleaned_daily_base p
    LEFT JOIN stock_info i ON p.StockID = i.symbol
    WHERE p.日期 = '{latest_date}' AND p.is_limit_up = 1
    ORDER BY p.Seq_LU_Count DESC, p.StockID ASC
    """
    df_today = pd.read_sql(query_today, conn)

    st.title(f"🚀 {market_option} 今日漲停戰情室 2.0")
    st.caption(f"📅 基準日：{latest_date} | 數據範圍：2023 至今 | 新增產業AI分析與一鍵生成")

    if df_today.empty:
        st.warning(f"⚠️ {latest_date} 此交易日尚無漲停股票數據。")
    else:
        # --- 第一部分：產業分析與AI提示詞自動生成 ---
        st.divider()
        st.subheader("📊 漲停產業別分析")
        
        # 產業分佈數據
        df_today['Sector'] = df_today['Sector'].fillna('未分類')
        sector_counts = df_today['Sector'].value_counts().reset_index()
        sector_counts.columns = ['產業別', '漲停家數']
        
        # 計算產業統計
        sector_stats = {}
        for sector in df_today['Sector'].unique():
            sector_stocks = df_today[df_today['Sector'] == sector]
            avg_seq = sector_stocks['Seq_LU_Count'].mean()
            sector_stats[sector] = {
                'count': len(sector_stocks),
                'avg_seq': round(avg_seq, 1),
                'stocks': sector_stocks[['StockID', 'Name', 'Seq_LU_Count']].to_dict('records')
            }
        
        col1, col2 = st.columns([1.2, 1])
        
        with col1:
            # 產業分佈圖
            fig = px.bar(sector_counts, x='漲停家數', y='產業別', orientation='h', 
                        color='漲停家數', color_continuous_scale='Reds',
                        title=f"{market_option}市場 今日漲停產業分佈")
            st.plotly_chart(fig, use_container_width=True)
            
            # 產業選擇與AI分析
            st.markdown("<div class='ai-section'>", unsafe_allow_html=True)
            st.subheader("🤖 產業AI分析")
            
            selected_sector = st.selectbox(
                "選擇產業進行AI分析：",
                options=sector_counts['產業別'].tolist(),
                key="sector_selector"
            )
            
            if selected_sector:
                # 自動生成該產業的AI提示詞
                sector_data = sector_stats[selected_sector]
                sector_stocks_list = df_today[df_today['Sector'] == selected_sector]
                
                # 建立產業股票表格
                sector_table = sector_stocks_list[['StockID', 'Name', 'Seq_LU_Count']].to_markdown(index=False)
                
                # 建立產業AI提示詞
                sector_prompt = f"""請擔任專業市場分析師，分析{market_option}市場的{selected_sector}產業：

## 產業概況
- **產業名稱**: {selected_sector}
- **今日漲停家數**: {sector_data['count']}家 (佔總漲停數 {round(sector_data['count']/len(df_today)*100, 1)}%)
- **平均連板天數**: {sector_data['avg_seq']}天

## 漲停個股詳情
{sector_table}

## 市場背景
- 分析日期: {latest_date}
- 總漲停家數: {len(df_today)}家
- 市場代號: {market_option}

## 分析問題
1. **產業熱度分析**:
   - 從漲停家數和連板天數來看，此產業目前處於什麼週期位置？
   - 是否有龍頭股帶動效應？（觀察連板天數最高的股票）

2. **資金流向解讀**:
   - 為什麼資金集中在此產業？可能的催化劑是什麼？
   - 此產業的漲停股票是否有共同特徵？（市值、成交額、技術形態等）

3. **風險評估**:
   - 此產業的連板效應是否過熱？回調風險有多高？
   - 歷史上類似產業集體漲停後，後續表現如何？

4. **投資建議**:
   - 對於已持有此產業股票的投資者，建議的操作策略？
   - 對於想追價的投資者，建議的進場時機和風險控制？
   
5. **產業聯動**:
   - 此產業的上游/下游是否有聯動效應？
   - 在當前市場環境下，此產業的持續性如何判斷？

請提供具體、可操作的投資建議。"""
                
                # 顯示提示詞和AI平台連結
                st.write(f"### 📋 {selected_sector} 產業分析提示詞")
                st.code(sector_prompt, language="text")
                
                # 一鍵帶入ChatGPT
                encoded_sector_prompt = urllib.parse.quote(sector_prompt)
                st.link_button(
                    f"🔥 一鍵帶入 ChatGPT 分析 {selected_sector}",
                    f"https://chatgpt.com/?q={encoded_sector_prompt}",
                    use_container_width=True,
                    help="自動在ChatGPT中打開此產業分析"
                )
                
                st.link_button(
                    "🔍 複製到 DeepSeek 分析",
                    "https://chat.deepseek.com/",
                    use_container_width=True,
                    help="請複製上方提示詞貼到DeepSeek"
                )
            
            st.markdown("</div>", unsafe_allow_html=True)
        
        with col2:
            st.subheader("📋 今日強勢清單")
            st.dataframe(df_today[['StockID', 'Name', 'Sector', 'Seq_LU_Count']], 
                        use_container_width=True, 
                        hide_index=True,
                        height=400)
            
            # 快速統計
            st.markdown("---")
            total_stocks = len(df_today)
            avg_lu = df_today['Seq_LU_Count'].mean()
            max_lu = df_today['Seq_LU_Count'].max()
            
            col_stat1, col_stat2 = st.columns(2)
            with col_stat1:
                st.metric("總漲停家數", f"{total_stocks}家")
            with col_stat2:
                st.metric("最高連板", f"{max_lu}天")
        
        # --- 第二部分：個股深度分析 ---
        st.divider()
        st.subheader("🎯 個股深度分析")
        
        df_today['select_label'] = df_today['StockID'] + " " + df_today['Name'].fillna("")
        selected_label = st.selectbox("請選擇要分析的漲停股：", 
                                     options=df_today['select_label'].tolist(),
                                     key="stock_selector")
        
        if selected_label:
            target_id = selected_label.split(" ")[0]
            stock_detail = df_today[df_today['StockID'] == target_id].iloc[0]

            # 聚合查詢
            backtest_q = f"""
            SELECT  
                SUM(is_limit_up) as total_lu,  
                SUM(CASE WHEN is_limit_up = 0 AND Ret_High > 0.095 THEN 1 ELSE 0 END) as total_failed,
                AVG(CASE WHEN Prev_LU = 1 THEN Overnight_Alpha END) as avg_open,
                AVG(CASE WHEN Prev_LU = 1 THEN Next_1D_Max END) as avg_max,
                AVG(CASE WHEN Prev_LU = 1 AND Next_1D_Ret < 0 THEN 1 ELSE 0 END) as next_day_loss_rate
            FROM cleaned_daily_base  
            WHERE StockID = '{target_id}'
            """
            bt = pd.read_sql(backtest_q, conn).iloc[0]
            
            # 獲取歷史連板記錄
            history_q = f"""
            SELECT 日期, Seq_LU_Count, Ret_Day
            FROM cleaned_daily_base
            WHERE StockID = '{target_id}' AND is_limit_up = 1
            ORDER BY 日期 DESC
            LIMIT 5
            """
            history_df = pd.read_sql(history_q, conn)

            # 顯示個股統計指標
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("今日狀態", f"{stock_detail['Seq_LU_Count']} 連板")
            m2.metric("2023至今漲停", f"{int(bt['total_lu'] or 0)} 次")
            m3.metric("2023至今炸板", f"{int(bt['total_failed'] or 0)} 次", delta_color="inverse")
            next_loss_rate = (bt['next_day_loss_rate'] or 0) * 100
            m4.metric("隔日下跌機率", f"{next_loss_rate:.1f}%", 
                     delta=f"溢價: {(bt['avg_open'] or 0)*100:.1f}%")
            
            # 💡 同族群聯動
            current_sector = stock_detail['Sector']
            related_q = f"""
            SELECT p.StockID, i.name as Name, p.is_limit_up, p.Seq_LU_Count
            FROM cleaned_daily_base p
            LEFT JOIN stock_info i ON p.StockID = i.symbol
            WHERE i.sector = '{current_sector}' AND p.日期 = '{latest_date}' AND p.StockID != '{target_id}'
            LIMIT 15
            """
            df_related = pd.read_sql(related_q, conn)
            
            st.write(f"🌿 **同產業聯動參考 ({current_sector})：**")
            if not df_related.empty:
                # 建立連結列表
                related_links = []
                for _, r in df_related.iterrows():
                    pure_symbol = r['StockID'].split('.')[0]
                    link_url = current_url_base.replace("{s}", pure_symbol)
                    status_icon = "🔥" if r['is_limit_up'] == 1 else "➡️"
                    seq_info = f" ({r['Seq_LU_Count']}板)" if r['Seq_LU_Count'] > 0 else ""
                    related_links.append(f"[{r['StockID']}{seq_info} {status_icon}]({link_url})")
                
                # 顯示產業聯動分析提示詞
                st.markdown(" ".join(related_links))
                
                # 自動生成同產業分析提示詞
                industry_stocks = df_related.copy()
                industry_stocks = industry_stocks[industry_stocks['is_limit_up'] == 1]
                
                if len(industry_stocks) > 0:
                    industry_table = industry_stocks[['StockID', 'Name', 'Seq_LU_Count']].to_markdown(index=False)
                    
                    industry_prompt = f"""分析{market_option}市場{current_sector}產業的連動效應：

核心個股：{selected_label} (連板{stock_detail['Seq_LU_Count']}天)
同產業漲停夥伴：{len(industry_stocks)}家

## 同產業漲停清單
{industry_table}

## 分析問題
1. **產業聯動強度**：從漲停家數看，{current_sector}是否形成板塊效應？
2. **龍頭辨識**：{target_id}是否是產業龍頭？從連板天數判斷。
3. **擴散效應**：產業內漲停是否從龍頭擴散到其他個股？
4. **風險評估**：產業集體漲停後，歷史回調風險如何？
5. **操作策略**：在產業聯動效應下，最佳進出場時機為何？

請提供具體的交易策略建議。"""
                    
                    encoded_industry_prompt = urllib.parse.quote(industry_prompt)
                    st.link_button(
                        f"🤝 分析{current_sector}產業聯動效應 (ChatGPT)",
                        f"https://chatgpt.com/?q={encoded_industry_prompt}",
                        use_container_width=True
                    )
            else:
                st.caption("暫無同產業其他公司數據")
            
            # --- 第三部分：AI 專家診斷 (自動生成+密碼保護Gemini) ---
            st.divider()
            st.subheader(f"🤖 AI 專家診斷：{stock_detail['Name']}")
            
            # 自動生成個股AI提示詞（無需按鈕）
            expert_prompt = f"""你是專業短線交易員。請深度分析股票 {selected_label}：

## 基本資料
- 市場：{market_option} | 產業：{current_sector}
- 今日狀態：連板第 {stock_detail['Seq_LU_Count']} 天
- 今日漲幅：{stock_detail['Ret_Day']*100:.2f}%

## 歷史統計數據
- 2023至今：漲停 {int(bt['total_lu'])} 次，衝板失敗(炸板) {int(bt['total_failed'])} 次。
- 隔日開盤溢價期望：{(bt['avg_open'] or 0)*100:.2f}%
- 隔日最高溢價期望：{(bt['avg_max'] or 0)*100:.2f}%
- 隔日下跌機率：{next_loss_rate:.1f}%

## 近期歷史漲停記錄
{history_df.to_markdown(index=False) if not history_df.empty else '無近期歷史記錄'}

## 技術分析維度
1. **連板天數解析**：當前{stock_detail['Seq_LU_Count']}連板在歷史中處於什麼位置？
2. **炸板率分析**：{int(bt['total_failed'])}次炸板顯示什麼籌碼特性？
3. **隔日溢價模式**：歷史數據顯示何種隔日開盤模式？

## 市場心理維度
4. **產業地位**：在同產業{current_sector}中的領導地位？
5. **市場情緒**：當前連板數反映的市場情緒溫度？
6. **風險偏好**：適合何種風險偏好的投資者？

## 風險控制建議
7. **最大風險**：最可能導致虧損的情境？
8. **停損策略**：基於歷史數據的最佳停損點位？
9. **資金配置**：建議的單筆投資比例？

## 具體操作建議
10. **進場時機**：明日開盤、盤中、還是等待回調？
11. **出場策略**：目標價位與持有時間建議？
12. **替代方案**：如果錯過此股，同產業其他選擇？

請提供量化、具體、可執行的交易計劃。"""

            # 顯示提示詞
            with st.expander("📋 查看完整AI分析提示詞", expanded=True):
                st.code(expert_prompt, language="text")
            
            # AI平台按鈕
            col_ai1, col_ai2 = st.columns(2)
            
            with col_ai1:
                # ChatGPT一鍵帶入
                encoded_prompt = urllib.parse.quote(expert_prompt)
                st.link_button(
                    "🔥 一鍵帶入 ChatGPT 分析",
                    f"https://chatgpt.com/?q={encoded_prompt}",
                    use_container_width=True,
                    help="自動在ChatGPT中打開此股票分析"
                )
            
            with col_ai2:
                st.link_button(
                    "🔍 複製到 DeepSeek 分析",
                    "https://chat.deepseek.com/",
                    use_container_width=True,
                    help="請複製上方提示詞貼到DeepSeek"
                )
            
            # Gemini內建診斷（密碼保護）
            if st.session_state.gemini_authorized:
                st.markdown("---")
                st.subheader("🔬 內建 Gemini 深度診斷")
                
                run_gemini = st.button("🚀 啟動 Gemini 專家診斷", use_container_width=True, type="primary")
                
                if run_gemini:
                    api_key = st.secrets.get("GEMINI_API_KEY")
                    if not api_key:
                        st.warning("⚠️ 請在secrets中設定 GEMINI_API_KEY")
                    else:
                        try:
                            genai.configure(api_key=api_key)
                            all_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                            
                            # 優先選擇可用的模型
                            target_model = None
                            for model_name in ['models/gemini-1.5-pro', 'models/gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-1.5-flash']:
                                if model_name in all_models:
                                    target_model = model_name
                                    break
                            
                            if not target_model and all_models:
                                target_model = all_models[0]
                            
                            if target_model:
                                model = genai.GenerativeModel(target_model)
                                
                                with st.spinner(f"🤖 Gemini 正在深度分析 ({target_model})..."):
                                    response = model.generate_content(expert_prompt)
                                    
                                    st.success("✅ Gemini 專家診斷報告")
                                    st.markdown("---")
                                    st.markdown(response.text)
                                    
                                    # 提供下載報告
                                    report_text = f"# {selected_label} AI診斷報告\n\n" + response.text
                                    st.download_button(
                                        label="📥 下載診斷報告",
                                        data=report_text.encode('utf-8'),
                                        file_name=f"ai_diagnosis_{target_id}.md",
                                        mime="text/markdown"
                                    )
                            else:
                                st.error("❌ 找不到可用的 Gemini 模型")
                        except Exception as e:
                            st.error(f"❌ AI 分析失敗: {str(e)}")
            else:
                st.info("🔒 Gemini 內建診斷需要授權解鎖，請在左側欄位輸入授權密碼。")
                
                # 在個股區域也提供授權按鈕
                with st.expander("🔐 在此處授權 Gemini"):
                    auth_pw = st.text_input("授權密碼：", type="password", key="stock_auth_pw")
                    if st.button("解鎖 Gemini", key="stock_auth_btn"):
                        if auth_pw == st.secrets.get("AI_ASK_PASSWORD", "default_password"):
                            st.session_state.gemini_authorized = True
                            st.rerun()
                        else:
                            st.error("密碼錯誤")
        
        # --- 第四部分：市場整體AI分析 ---
        st.divider()
        st.subheader("🌐 市場整體AI分析")
        
        # 自動生成市場整體分析提示詞
        market_summary = f"""
## {market_option}市場 今日漲停整體分析

### 市場概況
- 分析日期: {latest_date}
- 總漲停家數: {len(df_today)}家
- 平均連板天數: {avg_lu:.1f}天
- 最高連板: {max_lu}天

### 產業分佈
{sector_counts.to_markdown(index=False)}

### 連板天數分佈
{df_today['Seq_LU_Count'].value_counts().sort_index().to_markdown()}

### 市場分析問題
1. **市場熱度評估**：從漲停家數看，當前市場處於什麼情緒週期？
2. **產業輪動分析**：哪些產業是今日主流？是否有持續性？
3. **連板效應**：連板股票的分佈顯示什麼市場結構？
4. **風險提示**：市場過熱跡象有哪些？回調風險多高？
5. **策略建議**：在當前市場環境下，最佳交易策略為何？

請提供專業的市場分析與投資建議。"""
        
        with st.expander("📊 市場整體AI分析提示詞", expanded=False):
            st.code(market_summary, language="text")
            
            encoded_market = urllib.parse.quote(market_summary)
            st.link_button(
                "🌐 分析整體市場情緒 (ChatGPT)",
                f"https://chatgpt.com/?q={encoded_market}",
                use_container_width=True
            )

except Exception as e:
    st.error(f"錯誤: {e}")
finally:
    conn.close()

# --- 4. 底部導覽列 ---
st.divider()
st.markdown("### 🔗 快速資源連結")
col_link1, col_link2, col_link3 = st.columns(3)
with col_link1:
    st.page_link("https://vocus.cc/article/694f813afd8978000101e75a", 
                label="⚙️ 環境與 AI 設定教學", icon="🛠️")
with col_link2:
    st.page_link("https://vocus.cc/article/694f88bdfd89780001042d74", 
                label="📖 儀表板功能詳解", icon="📊")
with col_link3:
    st.page_link("https://github.com/grissomlin/Alpha-Data-Cleaning-Lab", 
                label="💻 GitHub 專案原始碼", icon="🐙")

# 版本資訊
st.caption("版本：全球漲停板 AI 分析儀 2.0 | 新增：產業AI分析、一鍵生成提示詞、密碼保護Gemini")
