# -*- coding: utf-8 -*-
import pandas as pd
import numpy as np
import sqlite3

class AlphaCoreEngine:
    def __init__(self, conn, rules, market_abbr):
        self.conn = conn
        self.rules = rules
        self.market_abbr = market_abbr.upper()
        self.df = None

    def execute(self):
        print(f"--- 🚀 啟動 {self.market_abbr} 數據精煉 ---")
        
        # 1. 讀取原始數據
        query = """
            SELECT date as 日期, symbol as StockID, open as 開盤, 
                   high as 最高, low as 最低, close as 收盤, volume as 成交量
            FROM stock_prices 
            WHERE date >= '2023-01-01'
        """
        try:
            self.df = pd.read_sql(query, self.conn)
            if self.df.empty:
                return f"Error: {self.market_abbr} No raw data found"
        except Exception as e:
            return f"Error: {e}"

        print(f"📊 讀入原始數據量: {len(self.df)} 筆。")

        # 2. 基礎預處理
        self.df = self.df.sort_values(['StockID', '日期']).reset_index(drop=True)
        self.df['日期'] = pd.to_datetime(self.df['日期'])
        
        # 3. 整合市場別資訊
        try:
            info_df = pd.read_sql("SELECT symbol as StockID, market as MarketType FROM stock_info", self.conn)
            self.df = pd.merge(self.df, info_df, on='StockID', how='left')
        except:
            self.df['MarketType'] = 'Unknown'

        # 4. 套用市場規則 (現在 US 市場會套用 10% 邏輯)
        self.df = self.rules.apply(self.df)
        
        # 5. 💡 興櫃補強邏輯 (僅限台灣市場執行)
        if self.market_abbr == "TW":
            self._apply_taiwan_rotc_adjustments()
        else:
            print(f"ℹ️  {self.market_abbr} 市場非興櫃制，跳過專屬強勢補強。")

        # 6. 計算技術指標
        self.calculate_returns()
        self.calculate_rolling_returns()
        self.calculate_period_returns()
        self.calculate_sequence_counts()
        self.calculate_risk_metrics_extended()
        
        # 7. 格式化輸出
        self.df['日期'] = self.df['日期'].dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # 8. 寫入資料庫
        print(f"💾 正在更新加工表 cleaned_daily_base...")
        self.df.to_sql("cleaned_daily_base", self.conn, if_exists="replace", index=False)
        
        # 9. 優化
        try:
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_date ON cleaned_daily_base (StockID, 日期)")
            self.conn.execute("VACUUM")
        except:
            pass
        
        return f"✅ {self.market_abbr} 精煉完成！"

    def _apply_taiwan_rotc_adjustments(self):
        """ 專門處理台股興櫃 10% 實體紅棒或強度判定 """
        prev_close = self.df.groupby('StockID')['收盤'].shift(1)
        ret_vs_prev = (self.df['收盤'] / prev_close) - 1
        ret_intraday = (self.df['收盤'] / self.df['開盤']) - 1 

        is_rotc = (self.df['MarketType'].isin(['興櫃', 'ROTC'])) | (self.df['StockID'].str.endswith('.TWO'))
        is_strong = (ret_vs_prev >= 0.098) | (ret_intraday >= 0.098)
        
        self.df.loc[is_rotc & is_strong, 'is_limit_up'] = 1
        print(f"📊 興櫃補強：已標註 {(is_rotc & is_strong).sum()} 筆 10% 強勢事件。")

    def calculate_returns(self):
        self.df['Prev_Close'] = self.df.groupby('StockID')['收盤'].shift(1)
        self.df['Ret_Day'] = (self.df['收盤'] / self.df['Prev_Close']) - 1
        self.df['Overnight_Alpha'] = (self.df['開盤'] / self.df['Prev_Close']) - 1
        self.df['Ret_High'] = (self.df['最高'] / self.df['Prev_Close']) - 1
        
    def calculate_rolling_returns(self):
        for d in [5, 20, 200]:
            self.df[f'Ret_{d}D'] = self.df.groupby('StockID')['收盤'].transform(lambda x: x / x.shift(d) - 1)

    def calculate_period_returns(self):
        temp_dt = pd.to_datetime(self.df['日期'])
        for p, label in [('W', '周'), ('M', '月')]:
            first = self.df.groupby(['StockID', temp_dt.dt.to_period(p)])['收盤'].transform('first')
            self.df[f'{label}累计漲跌幅'] = (self.df['收盤'] / first) - 1

    def calculate_sequence_counts(self):
        def get_sequence(series):
            blocks = (series != series.shift()).cumsum()
            return series * (series.groupby(blocks).cumcount() + 1)
        self.df['Seq_LU_Count'] = self.df.groupby('StockID')['is_limit_up'].transform(get_sequence)

    def calculate_risk_metrics_extended(self):
        for d in [10, 20]:
            self.df[f'volatility_{d}d'] = self.df.groupby('StockID')['Ret_Day'].transform(
                lambda x: x.rolling(d).std() * (252**0.5)
            )
