import os
import sqlite3
import pandas as pd
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.oauth2.service_account import Credentials
import io
import json

# 導入自定義模組
from market_rules import MarketRuleRouter
from core_engine import AlphaCoreEngine

class AlphaDataPipeline:
    def __init__(self, market_abbr):
        self.market_abbr = market_abbr.upper()  # 強制轉大寫確保匹配
        self.db_name = f"{self.market_abbr.lower()}_stock_warehouse.db"
        self.creds = self._load_credentials()
        self.service = build('drive', 'v3', credentials=self.creds)
        
        # 建立 ID 映射 (請確保 GitHub Secrets 名稱與此一致)
        self.file_id_map = {
            "TW": os.environ.get("TW_DB_ID"),
            "US": os.environ.get("US_DB_ID"),
            "JP": os.environ.get("JP_DB_ID"),
            "HK": os.environ.get("HK_DB_ID"),
            "KR": os.environ.get("KR_DB_ID"),
            "CN": os.environ.get("CN_DB_ID"),
        }

    def _load_credentials(self):
        # 從 GitHub Secrets 讀取服務帳號金鑰
        creds_json = os.environ.get("GDRIVE_SERVICE_ACCOUNT")
        if not creds_json:
            raise ValueError("❌ 找不到環境變數: GDRIVE_SERVICE_ACCOUNT")
        info = json.loads(creds_json)
        return Credentials.from_service_account_info(info)

    def download_db(self):
        file_id = self.file_id_map.get(self.market_abbr)
        if not file_id:
            # 輸出目前可用的 ID 幫助診斷
            available_ids = {k: v is not None for k, v in self.file_id_map.items()}
            raise ValueError(f"❌ 找不到市場 {self.market_abbr} 的 File ID。目前已載入的 ID 狀態: {available_ids}")
            
        print(f"📥 正在從 Google Drive 下載 {self.db_name} (ID: {file_id})...")
        request = self.service.files().get_media(fileId=file_id)
        fh = io.FileIO(self.db_name, 'wb')
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            if status:
                print(f"   > 下載進度: {int(status.progress() * 100)}%")
        print(f"✅ {self.db_name} 下載成功")

    def upload_db(self):
        """
        🚀 核心改進：使用 Resumable Upload 處理大檔案上傳 (解決 US/CN SSL 錯誤)
        """
        file_id = self.file_id_map.get(self.market_abbr)
        
        # 使用 MediaFileUpload 並啟用 resumable 功能
        media = MediaFileUpload(
            self.db_name, 
            mimetype='application/octet-stream',
            resumable=True,
            chunksize=5 * 1024 * 1024  # 5MB 分塊上傳
        )
        
        request = self.service.files().update(
            fileId=file_id,
            media_body=media
        )
        
        print(f"📤 正在上傳 {self.db_name} (可續傳模式)...")
        response = None
        while response is None:
            try:
                status, response = request.next_chunk()
                if status:
                    print(f"   > 上傳進度: {int(status.progress() * 100)}%")
            except Exception as e:
                print(f"⚠️ 上傳中斷，嘗試自動恢復: {e}")
        
        print(f"✅ {self.db_name} 更新至雲端成功")

    def run_process(self):
        """
        執行整個精煉流程
        """
        self.download_db()
        
        # 建立資料庫連線
        conn = sqlite3.connect(self.db_name)
        
        try:
            # 1. 獲取市場規則
            rules = MarketRuleRouter.get_rules(self.market_abbr)
            
            # 2. 初始化核心引擎
            engine = AlphaCoreEngine(conn, rules, self.market_abbr)
            
            # 3. 執行精煉 (計算 10/20/50D 指標與 VACUUM)
            summary_msg = engine.execute()
            
            # 關閉連線以解除檔案鎖定，準備上傳
            conn.close()
            
            # 4. 上傳資料庫
            self.upload_db()
            
            # 寫入摘要供 Telegram 模組讀取
            with open("summary.txt", "w", encoding="utf-8") as f:
                f.write(str(summary_msg))
                
            return summary_msg
            
        except Exception as e:
            if conn: conn.close()
            print(f"❌ 處理 {self.market_abbr} 時發生異常: {e}")
            raise e

if __name__ == "__main__":
    # 重要修正：移除預設值 "TW"，改由環境變數嚴格控制
    target_market = os.environ.get("MARKET_TYPE")
    
    if not target_market:
        print("❌ 致命錯誤：環境變數 MARKET_TYPE 未設定！")
        print(f"目前所有環境變數清單: {list(os.environ.keys())}")
        exit(1)
        
    print(f"🚀 --- 啟動市場精煉工廠: {target_market} ---")
    pipeline = AlphaDataPipeline(target_market)
    pipeline.run_process()
