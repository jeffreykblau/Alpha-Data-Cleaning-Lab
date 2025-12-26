import pandas as pd
import numpy as np

# 這裡名稱必須與 main_pipeline 呼叫的一致
class AlphaCoreEngine:
    def __init__(self, df):
        self.df = df

    def refine_all(self):
        """執行所有精煉任務"""
        if self.df.empty:
            return self.df
        
        # 確保排序
        self.df = self.df.sort_values(['StockID', '日期']).reset_index(drop=True)
        
        self.calculate_returns()
        self.calculate_sequence_counts() # 修正後的連板邏輯
        self.calculate_risk_metrics()
        
        return self.df

    def calculate_returns(self):
        self.df['Prev_Close'] = self.df.groupby('StockID')['收盤'].shift(1)
        self.df['Ret_Day'] = (self.df['收盤'] / self.df['Prev_Close']) - 1
        self.df['Overnight_Alpha'] = (self.df['開盤'] / self.df['Prev_Close']) - 1
        self.df['Next_1D_Max'] = (self.df['最高'] / self.df['Prev_Close']) - 1

    def calculate_sequence_counts(self):
        """
        修正連板次數：確保 is_limit_up 為 0 時會歸零
        """
        def get_sequence(series):
            # 建立區塊識別，狀態改變即增加
            blocks = (series != series.shift()).cumsum()
            # 區塊內計數
            cum_counts = series.groupby(blocks).cumcount() + 1
            # 非漲停日乘 0 歸零
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
