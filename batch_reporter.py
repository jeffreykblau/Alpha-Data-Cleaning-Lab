# -*- coding: utf-8 -*-
import os
import requests
import glob
from dotenv import load_dotenv

# 載入環境變數（支援本地 .env 檔案與 GitHub Actions 環境變數）
load_dotenv()

def send_final_summary():
    """
    彙整所有市場的處理摘要並發送至 Telegram
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("❌ 錯誤：找不到 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID")
        return

    # 🚀 強化搜尋邏輯：遞迴搜尋所有資料夾下的 summary_*.txt
    # 解決 GitHub Actions download-artifact 可能將檔案放入子資料夾的問題
    summary_files = glob.glob('**/summary_*.txt', recursive=True)
    
    # 過濾掉空路徑並排序
    summary_files = sorted([f for f in summary_files if os.path.isfile(f)])
    
    if not summary_files:
        print("⚠️ 沒有偵測到任何處理摘要檔案（summary_*.txt）。")
        # 列出當前目錄結構以利除錯
        print("當前目錄檔案清單：", os.listdir('.'))
        return

    print(f"📂 偵測到 {len(summary_files)} 個摘要檔案，準備彙整報告...")

    report_content = "📊 **Alpha-Data-Refinery-Global 執行報告**\n"
    report_content += "======================================\n"
    
    for file_path in summary_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                # 取得檔名作為小標題
                market_label = os.path.basename(file_path).replace('summary_', '').replace('.txt', '').upper()
                report_content += f"📍 **市場: {market_label}**\n{content}\n\n"
        except Exception as e:
            print(f"⚠️ 讀取檔案 {file_path} 失敗: {e}")
            
    report_content += "======================================\n"
    report_content += "✅ 全球數據精煉任務已全數完成。"

    # 發送至 Telegram API
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id, 
        "text": report_content, 
        "parse_mode": "Markdown"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=15)
        if response.status_code == 200:
            print("✨ 總結報告已成功發送至 Telegram")
        else:
            print(f"❌ Telegram 回傳錯誤 ({response.status_code}): {response.text}")
    except Exception as e:
        print(f"❌ Telegram 發送失敗: {e}")

if __name__ == "__main__":
    send_final_summary()
