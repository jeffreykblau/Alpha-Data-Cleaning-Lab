import pandas as pd
import numpy as np

class DataRefineryEngine:
    def __init__(self, df):
        self.df = df

    def refine_all(self):
        """
        執行所有精煉任務
        """
        if self.df.empty:
            return self.df
        
        # 1. 基礎排序：確保計算前日數據時順序正確
        self.df = self.df.sort_values(['StockID', '日期']).reset_index(drop=True)
        
        # 2. 計算核心報酬率 (以昨日收盤為基準)
        self.calculate_returns()
        
        # 3. 計算連板次數 (修正歸零邏輯)
        self.calculate_sequence_counts()
        
        # 4. 計算風險指標 (波動率與回撤)
        self.calculate_risk_metrics()
        
        return self.df

    def calculate_returns(self):
        """
        計算正確的漲跌幅與隔日溢價
        """
        # 獲取昨日收盤 (用於判定漲停與計算報酬)
        self.df['Prev_Close'] = self.df.groupby('StockID')['收盤'].shift(1)
        
        # 正確的漲跌幅：(今日收盤 / 昨日收盤) - 1
        self.df['Ret_Day'] = (self.df['收盤'] / self.df['Prev_Close']) - 1
        
        # 隔日溢價 (Overnight Alpha)：(今日開盤 / 昨日收盤) - 1
        self.df['Overnight_Alpha'] = (self.df['開盤'] / self.df['Prev_Close']) - 1
        
        # 盤中摸頂空間 (Next_1D_Max)：(今日最高 / 昨日收盤) - 1
        self.df['Next_1D_Max'] = (self.df['最高'] / self.df['Prev_Close']) - 1

    def calculate_sequence_counts(self):
        """
        計算連板次數 (Seq_LU_Count)
        核心邏輯：利用 cumsum 建立區塊，當 is_limit_up 為 0 時強制乘法歸零
        """
        def get_sequence(series):
            # 建立區塊識別碼：當漲停狀態改變時，代碼會增加
            # 例如：1, 1, 0, 1, 1 -> 區塊編號 1, 1, 2, 3, 3
            blocks = (series != series.shift()).cumsum()
            
            # 在每個區塊內進行累計計數 (1, 2, 1, 1, 2)
            cum_counts = series.groupby(blocks).cumcount() + 1
            
            # 如果當天不是漲停 (series=0)，結果就會是 0 * 計數 = 0 (歸零成功！)
            return series * cum_counts

        self.df['Seq_LU_Count'] = self.df.groupby('StockID')['is_limit_up'].transform(get_sequence)

    def calculate_risk_metrics(self):
        """
        計算波動率與回撤
        """
        # 20日滾動波動率 (年化)
        self.df['volatility_20d'] = self.df.groupby('StockID')['Ret_Day'].transform(
            lambda x: x.rolling(window=20).std() * (252**0.5)
        )
        
        # 20日最大回撤 (從近期高點拉回的幅度)
        self.df['rolling_max_20d'] = self.df.groupby('StockID')['收盤'].transform(
            lambda x: x.rolling(window=20, min_periods=1).max()
        )
        self.df['drawdown_after_high_20d'] = (self.df['收盤'] / self.df['rolling_max_20d']) - 1

# 輔助函數：執行精煉任務
def start_refining(df):
    engine = DataRefineryEngine(df)
    return engine.refine_all()
