# -*- coding: utf-8 -*-
import pandas as pd
import numpy as np

class AlphaCoreEngine:
    def __init__(self, conn, rules, market_abbr):
        self.conn = conn
        self.rules = rules
        self.market_abbr = market_abbr

    def execute(self):
        # --- [新增] 自動偵測資料表名稱邏輯 ---
        # 取得資料庫中所有的資料表清單
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [t[0] for t in cursor.fetchall()]
        
        # 排除我們之後要產出的新表，找出原始資料表
        # 優先找 daily_prices，若無則取第一個非新表的表
        target_table = None
        if 'daily_prices' in tables:
            target_table = 'daily_prices'
        else:
            filtered_tables = [t for t in tables if t != 'cleaned_daily_base']
            if filtered_tables:
                target_table = filtered_tables[0]
        
        if not target_table:
            raise ValueError(f"❌ {self.market_abbr}: 資料庫中找不到任何原始資料表！")
        
        print(f"🔍 {self.market_abbr}: 偵測到原始資料表為 '{target_table}'")

        # 1. 讀取與排序
        df = pd.read_sql(f"SELECT * FROM {target_table}", self.conn)
        # ------------------------------------

        df['日期'] = pd.to_datetime(df['日期'])
        df = df.sort_values(['StockID', '日期']).reset_index(drop=True)

        # 2. 清洗與基礎指標
        df = self._clean_data(df)
        df = self._calculate_base_metrics(df)

        # 3. 國別漲跌停判定 (會產出 is_limit_up, Limit_Price, is_anomaly)
        df = self.rules.apply(df)

        # 4. 漲停行為分類 (LU_Type4) 與 隔日沖死法 (Fail_Type)
        df = self._calculate_pattern_analysis(df)

        # 5. 未來報酬分佈 (隔日, 5D, 6-10D, 11-20D)
        df = self._calculate_forward_returns(df)

        # 6. 存入資料庫 (這裡統一存成新表 cleaned_daily_base)
        df.to_sql("cleaned_daily_base", self.conn, if_exists='replace', index=False)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_sid_date ON cleaned_daily_base (StockID, 日期)")
        
        return f"{self.market_abbr}: 處理 {len(df)} 筆, 偵測漲停 {df['is_limit_up'].sum()} 筆"

    # ... (其餘 _clean_data, _calculate_base_metrics 等函數保持不變) ...
