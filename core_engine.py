import pandas as pd
import numpy as np
import json

class AlphaCoreEngine:
    def __init__(self, conn, rules, market_abbr):
        self.conn = conn
        self.rules = rules
        self.market_abbr = market_abbr
        self.df = None

    def execute(self):
        """
        執行清洗並回傳 summary
        """
        # 1. 讀取數據
        self.df = pd.read_sql("SELECT * FROM cleaned_daily_base", self.conn)
        
        if self.df.empty:
            return f"Market {self.market_abbr}: No data found."

        # 2. 排序與規則套用
        self.df = self.df.sort_values(['StockID', '日期']).reset_index(drop=True)
        self.df = self.rules.apply(self.df)
        
        # 3. 核心計算 (連板歸零邏輯)
        self.calculate_returns()
        self.calculate_sequence_counts() 
        self.calculate_risk_metrics()
        
        # 4. 寫回資料庫
        self.df.to_sql("cleaned_daily_base", self.conn, if_exists="replace", index=False)
        
        # 5. 構建 summary
        # 由於 main_pipeline 第 73 行執行 f.write(summary_msg)
        # 我們回傳一個格式化好的字串，這樣就不會噴 TypeError
        limit_up_total = int(self.df['is_limit_up'].sum())
        max_seq = int(self.df['Seq_LU_Count'].max())
        
        summary_text = (
            f"🚩 Market: {self.market_abbr}\n"
            f"📊 Total Records: {len(self.df)}\n"
            f"📈 Limit Up Count: {limit_up_total}\n"
            f"🚀 Max Sequence: {max_seq}\n"
            f"✅ Status: Success\n"
        )
        
        return summary_text

    def calculate_returns(self):
        self.df['Prev_Close'] = self.df.groupby('StockID')['收盤'].shift(1)
        self.df['Ret_Day'] = (self.df['收盤'] / self.df['Prev_Close']) - 1
        self.df['Overnight_Alpha'] = (self.df['開盤'] / self.df['Prev_Close']) - 1
        self.df['Next_1D_Max'] = (self.df['最高'] / self.df['Prev_Close']) - 1

    def calculate_sequence_counts(self):
        def get_sequence(series):
            blocks = (series != series.shift()).cumsum()
            cum_counts = series.groupby(blocks).cumcount() + 1
            return series * cum_counts
        self.df['Seq_LU_Count'] = self.df.groupby('StockID')['is_limit_up'].transform(get_sequence)

    def calculate_risk_metrics(self):
        self.df['volatility_20d'] = self.df.groupby('StockID')['Ret_Day'].transform(
            lambda x: x.rolling(window=20).std() * (252**0.5)
        )
        self.df['rolling_max_20d'] = self.df.groupby('StockID')['收盤'].transform(
            lambda x: x.rolling(window=20, min_periods=1).max()
        )
        self.df['drawdown_after_high_20d'] = (self.df['收盤'] / self.df['rolling_max_20d']) - 1
