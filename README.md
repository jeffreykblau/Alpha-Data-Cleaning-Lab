# 🚀 Alpha-Data-Cleaning-Lab

**Alpha-Data-Cleaning-Lab** 是一個基於 Streamlit 開發的全球股市大數據分析儀表板。結合了 Google Gemini AI 的強大診斷能力，幫助投資者從雜亂的市場數據中快速萃取關鍵洞察。

---

## 📖 快速上手與文件

為了讓您能更順利地架設並使用本系統，建議先閱讀以下在方格子（vocus）上的詳細教學：

* 🛠️ **環境與 AI 設定教學**：[點此閱讀文章](https://vocus.cc/article/694f813afd8978000101e75a)
* 📊 **儀表板功能詳解**：[點此閱讀文章](https://vocus.cc/article/694f88bdfd89780001042d74)

---

## ✨ 核心功能

### 🌎 全球強勢股產業連動監測 (`Global_Trend.py`)
* **跨國數據同步**：支援 TW, US, CN, JP, HK, KR 六大市場。
* **資金流向偵測**：篩選漲幅 > 10% 的個股，並按產業分類呈現。
* **AI 宏觀診斷**：利用 Gemini 分析全球產業趨勢與聯動效應。

### 🔍 AI 綜合個股深度掃描 (`Deep_Scan.py`)
* **多維體質評分**：自動生成動能、穩定度、防禦力的雷達圖。
* **股性大數據**：統計 2023 至今的成功漲停次數與「炸板」紀錄。
* **專家診斷報告**：AI 針對個股籌碼壓力與妖性給予短線操作建議。

### 🚀 今日漲停戰情室 (`Today_Limit_Up.py`)
* **連板追蹤**：自動標記個股連板天數。
* **溢價期望值**：計算歷史漲停後隔日的開盤溢價均值。
* **同族群聯動**：即時顯示同產業中其他強勢個股。

### 🛡️ 風險指標深度掃描 (`Risk_Metrics.py`)
* **最大回撤分析**：視覺化呈現市場 10D/20D 的拉回風險分佈。
* **抗跌韌性區**：自動過濾出月報酬為正且回撤極小的穩定標的。

### 📈 長周期與滾動漲跌分析 (`Period_Analysis.py`)
* **九宮格動能分佈**：一次掌握 5D/20D/200D 與周月年累計報酬。
* **強勢分箱清單**：將市場個股分類為「噴發」、「強勢」至「慘跌」等級。

---

## ⚙️ 環境變數設定 (.env / Secrets)

請在專案根目錄建立 `.env` 檔案，或在 Streamlit Cloud 的 Secrets 中設定以下變數：

```toml
# 核心大腦 (必填)
GEMINI_API_KEY = "您的_Gemini_API_Key"

# Google Drive 資料庫同步 (選配)
GDRIVE_SERVICE_ACCOUNT = "您的_Service_Account_JSON_字串"

# 通知系統 (選配)
TELEGRAM_BOT_TOKEN = "您的_Telegram_Token"
RESEND_API_KEY = "您的_Resend_API_Key"
