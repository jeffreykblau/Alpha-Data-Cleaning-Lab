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
        執行精煉任務，補全週期分析與風險指標(10D, 20D, 50D)
        """
        self.df = pd.read_sql("SELECT * FROM cleaned_daily_base", self.conn)
        
        if self.df.empty:
            return f"Market {self.market_abbr}: No data."

        # 基礎預處理
        self.df = self.df.sort_values(['StockID', '日期']).reset_index(drop=True)
        self.df['日期'] = pd.to_datetime(self.df['日期'])
        
        # 1. 判定漲停 (修正標記，解決 ETF 問題)
        self.df = self.rules.apply(self.df)
        
        # 2. 計算所有報酬與週期指標
        self.calculate_returns()           # 基礎報酬
        self.calculate_rolling_returns()    # Ret_5D, 20D, 200D
        self.calculate_period_returns()     # 周/月/年累積
        self.calculate_sequence_counts()    # 連板重置
        
        # 3. 計算風險指標 (補齊 10D, 20D, 50D)
        self.calculate_risk_metrics_extended()
        
        # 4. 轉換日期格式並寫回
        self.df['日期'] = self.df['日期'].dt.strftime('%Y-%m-%d %H:%M:%S')
        self.df.to_sql("cleaned_daily_base", self.conn, if_exists="replace", index=False)
        
        return f"✅ {self.market_abbr} 精煉完成，已補齊風險與週期欄位。"

    def calculate_returns(self):
        self.df['Prev_Close'] = self.df.groupby('StockID')['收盤'].shift(1)
        self.df['Ret_Day'] = (self.df['收盤'] / self.df['Prev_Close']) - 1
        self.df['Overnight_Alpha'] = (self.df['開盤'] / self.df['Prev_Close']) - 1
        self.df['Next_1D_Max'] = (self.df['最高'] / self.df['Prev_Close']) - 1

    def calculate_rolling_returns(self):
        for d in [5, 20, 200]:
            self.df[f'Ret_{d}D'] = self.df.groupby('StockID')['收盤'].transform(lambda x: x / x.shift(d) - 1)

    def calculate_period_returns(self):
        temp_dt = pd.to_datetime(self.df['日期'])
        # 周累積
        week_first = self.df.groupby(['StockID', temp_dt.dt.to_period('W')])['收盤'].transform('first')
        self.df['周累计漲跌幅(本周开盘)'] = (self.df['收盤'] / week_first) - 1
        # 月累積 (Ret_M)
        month_first = self.df.groupby(['StockID', temp_dt.dt.to_period('M')])['收盤'].transform('first')
        self.df['月累计漲跌幅(本月开盘)'] = (self.df['收盤'] / month_first) - 1
        # 年累積
        year_first = self.df.groupby(['StockID', temp_dt.dt.year])['收盤'].transform('first')
        self.df['年累計漲跌幅(本年开盘)'] = (self.df['收盤'] / year_first) - 1

    def calculate_sequence_counts(self):
        def get_sequence(series):
            blocks = (series != series.shift()).cumsum()
            return series * (series.groupby(blocks).cumcount() + 1)
        self.df['Seq_LU_Count'] = self.df.groupby('StockID')['is_limit_up'].transform(get_sequence)

    def calculate_risk_metrics_extended(self):
        """
        對齊 Risk_Metrics 頁面的 SQL 需求：10D, 20D, 50D
        """
        for d in [10, 20, 50]:
            # 波動率 (年化)
            self.df[f'volatility_{d}d'] = self.df.groupby('StockID')['Ret_Day'].transform(
                lambda x: x.rolling(d).std() * (252**0.5)
            )
            # 最大回撤
            rolling_max = self.df.groupby('StockID')['收盤'].transform(lambda x: x.rolling(d, min_periods=1).max())
            self.df[f'drawdown_after_high_{d}d'] = (self.df['收盤'] / rolling_max) - 1
            
        # 計算 recovery_from_dd_10d (當前價格相對於 10D 最低點的反彈程度)
        rolling_min_10d = self.df.groupby('StockID')['收盤'].transform(lambda x: x.rolling(10, min_periods=1).min())
        self.df['recovery_from_dd_10d'] = (self.df['收盤'] / rolling_min_10d) - 1
