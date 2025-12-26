import pandas as pd
import numpy as np

class AlphaCoreEngine:
    def __init__(self, conn, rules, market_abbr):
        self.conn = conn
        self.rules = rules
        self.market_abbr = market_abbr
        self.df = None

    def execute(self):
        """
        對應 main_pipeline.py 第 56 行的呼叫
        執行清洗並回傳 summary 字典
        """
        # 1. 讀取數據
        self.df = pd.read_sql("SELECT * FROM cleaned_daily_base", self.conn)
        
        if self.df.empty:
            return {"status": "empty", "count": 0}

        initial_count = len(self.df)
        
        # 2. 排序與規則套用 (昨日收盤基準)
        self.df = self.df.sort_values(['StockID', '日期']).reset_index(drop=True)
        self.df = self.rules.apply(self.df)
        
        # 3. 核心計算
        self.calculate_returns()
        self.calculate_sequence_counts() # 解決 1454 連板歸零邏輯
        self.calculate_risk_metrics()
        
        # 4. 將清洗後的結果寫回資料庫 (覆蓋舊表)
        self.df.to_sql("cleaned_daily_base", self.conn, if_exists="replace", index=False)
        
        # 5. 構建 summary 字典回傳給 pipeline
        summary = {
            "market": self.market_abbr,
            "total_records": len(self.df),
            "limit_up_count": int(self.df['is_limit_up'].sum()),
            "max_sequence": int(self.df['Seq_LU_Count'].max()),
            "status": "success"
        }
        
        return summary

    def calculate_returns(self):
        # 使用昨日收盤 Prev_Close 作為所有報酬率的分母
        self.df['Prev_Close'] = self.df.groupby('StockID')['收盤'].shift(1)
        self.df['Ret_Day'] = (self.df['收盤'] / self.df['Prev_Close']) - 1
        self.df['Overnight_Alpha'] = (self.df['開盤'] / self.df['Prev_Close']) - 1
        self.df['Next_1D_Max'] = (self.df['最高'] / self.df['Prev_Close']) - 1

    def calculate_sequence_counts(self):
        """
        連板歸零重置邏輯：解決 ETF 異常連板
        """
        def get_sequence(series):
            blocks = (series != series.shift()).cumsum()
            cum_counts = series.groupby(blocks).cumcount() + 1
            return series * cum_counts

        self.df['Seq_LU_Count'] = self.df.groupby('StockID')['is_limit_up'].transform(get_sequence)

    def calculate_risk_metrics(self):
        # 20日波動率與回撤
        self.df['volatility_20d'] = self.df.groupby('StockID')['Ret_Day'].transform(
            lambda x: x.rolling(window=20).std() * (252**0.5)
        )
        self.df['rolling_max_20d'] = self.df.groupby('StockID')['收盤'].transform(
            lambda x: x.rolling(window=20, min_periods=1).max()
        )
        self.df['drawdown_after_high_20d'] = (self.df['收盤'] / self.df['rolling_max_20d']) - 1
