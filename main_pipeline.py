# -*- coding: utf-8 -*-
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
        self.market_abbr = market_abbr.upper()
        self.db_name = f"{self.market_abbr.lower()}_stock_warehouse.db"
        self.creds = self._load_credentials()
        self.service = build('drive', 'v3', credentials=self.creds)

    def _load_credentials(self):
        creds_json = os.environ.get("GDRIVE_SERVICE_ACCOUNT")
        if not creds_json:
            raise ValueError("❌ 找不到環境變數: GDRIVE_SERVICE_ACCOUNT")
        return Credentials.from_service_account_info(json.loads(creds_json))

    def find_file_id_by_name(self, filename):
        query = f"name = '{filename}' and trashed = false"
        results = self.service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get('files', [])
        if not files:
            raise ValueError(f"❌ 在雲端找不到檔案: {filename}")
        return files[0]['id']

    def download_db(self):
        file_id = self.find_file_id_by_name(self.db_name)
        print(f"📥 偵測到雲端檔案 ID: {file_id}，開始下載...")
        request = self.service.files().get_media(fileId=file_id)
        fh = io.FileIO(self.db_name, 'wb')
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        print(f"✅ {self.db_name} 下載成功")

    def _ensure_schema_upgraded(self, conn):
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(cleaned_daily_base)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'Ret_High' not in columns:
            print(f"🛠️  正在為 {self.market_abbr} 資料庫新增 Ret_High 欄位...")
            try:
                cursor.execute("ALTER TABLE cleaned_daily_base ADD COLUMN Ret_High REAL")
                conn.commit()
                print("✅ 欄位新增成功")
            except Exception as e:
                print(f"⚠️ 欄位新增異常 (可能已存在): {e}")

    def upload_db(self):
        file_id = self.find_file_id_by_name(self.db_name)
        media = MediaFileUpload(self.db_name, mimetype='application/octet-stream', resumable=True)
        request = self.service.files().update(fileId=file_id, media_body=media)
        
        print(f"📤 正在同步回雲端 (可續傳模式)...")
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"   > 進度: {int(status.progress() * 100)}%")
        print(f"✅ {self.market_abbr} 雲端同步成功")

    def run_process(self):
        """
        🚀 整合後的執行流程：下載 -> 偵察日期 -> 計算 -> 上傳
        """
        # 1. 下載雲端 DB
        self.download_db()
        
        conn = sqlite3.connect(self.db_name)
        try:
            # 💡 [新增] 資料狀態偵察：檢查原始資料 vs 加工資料
            cursor = conn.cursor()
            
            # 檢查原始價格 (stock_prices)
            cursor.execute("SELECT MAX(date) FROM stock_prices")
            raw_date = cursor.fetchone()[0]
            
            # 檢查加工特徵 (cleaned_daily_base)
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cleaned_daily_base'")
            if cursor.fetchone():
                # 偵測日期欄位（處理不同市場可能叫 'date' 或 '日期' 的情況）
                cursor.execute("PRAGMA table_info(cleaned_daily_base)")
                cols = [c[1] for c in cursor.fetchall()]
                date_col = '日期' if '日期' in cols else 'date'
                
                cursor.execute(f"SELECT MAX([{date_col}]) FROM cleaned_daily_base")
                clean_date_raw = cursor.fetchone()[0]
                # 處理帶有時分秒的字串 (例如 2025-12-24 00:00:00 -> 2025-12-24)
                clean_date = str(clean_date_raw).split(' ')[0] if clean_date_raw else "N/A"
            else:
                clean_date = "資料表尚未建立"

            print("\n" + "="*50)
            print(f"🔍 [{self.market_abbr}] 數據一致性偵察：")
            print(f"📅 原始股價 (stock_prices) 最新日期: {raw_date}")
            print(f"📊 加工指標 (cleaned_daily_base) 最新日期: {clean_date}")
            
            if raw_date == clean_date:
                print(f"✅ 兩者日期一致。")
            else:
                print(f"🚀 偵測到日期差！準備將加工表更新至 {raw_date}")
            print("="*50 + "\n")

            # 2. 自動升級資料庫結構
            self._ensure_schema_upgraded(conn)

            # 3. 執行核心精煉引擎 (計算技術指標、Alpha 標籤等)
            print(f"⚙️  啟動 AlphaCoreEngine 進行數據精煉...")
            rules = MarketRuleRouter.get_rules(self.market_abbr)
            engine = AlphaCoreEngine(conn, rules, self.market_abbr)
            summary_msg = engine.execute()
            
            # 重要：先關閉連線，確保檔案未被鎖定，才能順利上傳
            conn.close()
            
            # 4. 同步上傳回雲端
            self.upload_db()
            
            # 5. 生成摘要報告
            summary_file = f"summary_{self.db_name.replace('.db', '')}.txt"
            with open(summary_file, "w", encoding="utf-8") as f:
                f.write(str(summary_msg))
            
            print(f"📄 摘要報告已生成: {summary_file}")
            return summary_msg

        except Exception as e:
            if conn:
                conn.close()
            print(f"❌ 流程執行失敗: {e}")
            raise e

if __name__ == "__main__":
    target_market = os.environ.get("MARKET_TYPE")
    if not target_market:
        print("❌ 錯誤：未設定 MARKET_TYPE")
        exit(1)
    
    pipeline = AlphaDataPipeline(target_market)
    pipeline.run_process()
