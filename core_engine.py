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
        執行精煉任務，補全所有週期分析與連板重置欄位
        """
        # 1. 讀取數據 (根據你的結構，StockID 和 日期 是關鍵)
        self.df = pd.read_sql("SELECT * FROM cleaned_daily_base", self.conn)
        
        if self.df.empty:
            return f"Market {self.market_abbr}: No data found."

        # 基礎預處理
        self.df = self.df.sort_values(['StockID', '日期']).reset_index(drop=True)
        # 確保日期格式
        self.df['日期'] = pd.to_datetime(self.df['日期'])
        
        # 2. 判定漲停 (修正標記，解決 ETF 誤判問題)
        self.df = self.rules.apply(self.df)
        
        # 3. 核心計算
        self.calculate_returns()           # 基礎報酬
        self.calculate_rolling_returns()    # Ret_5D, Ret_20D, Ret_200D
        self.calculate_period_returns()     # 周/月/年累積
        self.calculate_sequence_counts()    # 連板重置 (解決 1454 問題)
        self.calculate_risk_metrics()       # 波動率與回撤
        
        # 4. 轉換日期回字串以符合 SQLite 原始儲存格式
        self.df['日期'] = self.df['日期'].dt.strftime('%Y-%m-%d %H:%M:%S')

        # 5. 寫回資料庫 (replace 確保欄位更新)
        self.df.to_sql("cleaned_daily_base", self.conn, if_exists="replace", index=False)
        
        # 6. 回傳字串摘要 (解決 main_pipeline.py TypeError)
        limit_up_total = int(self.df['is_limit_up'].sum())
        max_seq = int(self.df['Seq_LU_Count'].max())
        summary_text = (
            f"✅ {self.market_abbr} 精煉完成！\n"
            f"📊 總筆數: {len(self.df)}\n"
            f"📈 漲停總數: {limit_up_total}\n"
            f"🚀 最大連板: {max_seq}\n"
        )
        return summary_text

    def calculate_returns(self):
        # 使用 Prev_Close (你的資料表已有此欄位名)
        self.df['Prev_Close'] = self.df.groupby('StockID')['收盤'].shift(1)
        self.df['Ret_Day'] = (self.df['收盤'] / self.df['Prev_Close']) - 1
        self.df['Overnight_Alpha'] = (self.df['開盤'] / self.df['Prev_Close']) - 1
        self.df['Next_1D_Max'] = (self.df['最高'] / self.df['Prev_Close']) - 1

    def calculate_rolling_returns(self):
        """補齊 Ret_5D, Ret_20D, Ret_200D"""
        for d in [5, 20, 200]:
            self.df[f'Ret_{d}D'] = self.df.groupby('StockID')['收盤'].transform(
                lambda x: x / x.shift(d) - 1
            )

    def calculate_period_returns(self):
        """精確對齊 SQL 報錯中的中文欄位名稱"""
        temp_dt = pd.to_datetime(self.df['日期'])
        
        # 周累積 (本周開盤價定義為本周第一筆收盤)
        week_first = self.df.groupby(['StockID', temp_dt.dt.to_period('W')])['收盤'].transform('first')
        self.df['周累计漲跌幅(本周开盘)'] = (self.df['收盤'] / week_first) - 1
        
        # 月累積
        month_first = self.df.groupby(['StockID', temp_dt.dt.to_period('M')])['收盤'].transform('first')
        self.df['月累计漲跌幅(本月开盘)'] = (self.df['收盤'] / month_first) - 1
        
        # 年累積
        year_first = self.df.groupby(['StockID', temp_dt.dt.year])['收盤'].transform('first')
        self.df['年累計漲跌幅(本年开盘)'] = (self.df['收盤'] / year_first) - 1

    def calculate_sequence_counts(self):
        """修正連板邏輯：非漲停日乘 0 歸零"""
        def get_sequence(series):
            blocks = (series != series.shift()).cumsum()
            return series * (series.groupby(blocks).cumcount() + 1)
        self.df['Seq_LU_Count'] = self.df.groupby('StockID')['is_limit_up'].transform(get_sequence)

    def calculate_risk_metrics(self):
        # 20日波動率
        self.df['volatility_20d'] = self.df.groupby('StockID')['Ret_Day'].transform(
            lambda x: x.rolling(20).std() * (252**0.5)
        )
        # 20日最大回撤
        self.df['rolling_max_20d'] = self.df.groupby('StockID')['收盤'].transform(
            lambda x: x.rolling(20, min_periods=1).max()
        )
        self.df['drawdown_after_high_20d'] = (self.df['收盤'] / self.df['rolling_max_20d']) - 1
