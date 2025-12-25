# -*- coding: utf-8 -*-
import pandas as pd
import numpy as np

class AlphaCoreEngine:
    def __init__(self, conn, rules, market_abbr):
        self.conn = conn
        self.rules = rules
        self.market_abbr = market_abbr

    def execute(self):
        # 1. 使用 JOIN 合併價格與市場資訊 (解決台股市場別判定問題)
        query = """
        SELECT p.*, i.market as MarketType
        FROM stock_prices p
        LEFT JOIN stock_info i ON p.symbol = i.symbol
        """
        print(f"📡 {self.market_abbr}: 執行資料關聯讀取...")
        df = pd.read_sql(query, self.conn)

        # 2. 統一欄位名稱映射 (將英文映射至邏輯需要的名稱)
        rename_map = {
            'date': '日期', 'symbol': 'StockID', 
            'open': '開盤', 'high': '最高', 'low': '最低', 
            'close': '收盤', 'volume': '成交量'
        }
        df = df.rename(columns=rename_map)

        # 3. 資料預處理 (排除 None 與 異常值)
        df['日期'] = pd.to_datetime(df['日期'], errors='coerce')
        df = df.dropna(subset=['日期', '收盤'])
        df = df.sort_values(['StockID', '日期']).reset_index(drop=True)
        
        if df.empty:
            return f"{self.market_abbr}: 警告 - 過濾後無有效資料"

        # 4. 基礎指標與清洗
        df['PrevClose'] = df.groupby('StockID')['收盤'].shift(1)
        df['Ret_Day'] = df['收盤'] / df['PrevClose'] - 1
        df['Vol_MA5'] = df.groupby('StockID')['成交量'].transform(lambda x: pd.to_numeric(x, errors='coerce').rolling(5).mean())
        df['Vol_Ratio'] = df['成交量'] / df.groupby('StockID')['Vol_MA5'].shift(1)

        # 5. 國別漲跌停判定 (is_limit_up, Limit_Price, is_anomaly)
        df = self.rules.apply(df)

        # 6. 漲停行為分類 (LU_Type4) 與 隔日沖死法 (Fail_Type)
        # 確保必要欄位存在
        df['Prev_LU'] = df.groupby('StockID')['is_limit_up'].shift(1).fillna(False)
        df['Overnight_Alpha'] = (df['開盤'] / df['PrevClose'] - 1).where(df['Prev_LU'])
        
        df['LU_Type4'] = df.apply(lambda r: self.rules.classify_lu_type4(r, r.get('Limit_Price', 0)) if r['is_limit_up'] else 0, axis=1)
        df['Fail_Type'] = df.apply(lambda r: self.rules.classify_fail_type(r) if r['Prev_LU'] else 0, axis=1)
        
        # 7. 未來報酬極值計算 (1D, 5D, 11-20D)
        df = self._calculate_forward_returns(df)

        # 8. 存入新表
        df.to_sql("cleaned_daily_base", self.conn, if_exists='replace', index=False)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_sid_date ON cleaned_daily_base (StockID, 日期)")
        
        return f"{self.market_abbr}: 精煉 {len(df)} 筆, 偵測漲停 {df['is_limit_up'].sum()} 筆"

    def _calculate_forward_returns(self, df):
        def get_fwd(col, s, w):
            return df.groupby('StockID')[col].shift(-s).rolling(w, min_periods=1)
        
        df['Next_1D_Max'] = (df.groupby('StockID')['最高'].shift(-1) / df['收盤']) - 1
        df['Fwd_5D_Max'] = (get_fwd('最高', 1, 5).max() / df['收盤']) - 1
        df['Fwd_5D_Min'] = (get_fwd('最低', 1, 5).min() / df['收盤']) - 1
        df['Fwd_11_20D_Max'] = (get_fwd('最高', 11, 10).max() / df['收盤']) - 1
        return df
