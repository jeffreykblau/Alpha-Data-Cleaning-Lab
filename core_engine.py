import pandas as pd
import numpy as np
import sqlite3

class AlphaCoreEngine:
    def __init__(self, conn, rules, market_abbr):
        self.conn = conn
        self.rules = rules
        self.market_abbr = market_abbr
        self.df = None

    def execute(self):
        print(f"--- 🚀 啟動 {self.market_abbr} 增量精煉 (2023至今) ---")
        
        # 1. 建立索引 (如果不存在)，加速讀取
        try:
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_date ON cleaned_daily_base (StockID, 日期)")
        except: pass

        # 2. 限制讀取規模：只讀取 2023-01-01 以後的數據
        cutoff_date = "2023-01-01"
        query = f"SELECT * FROM cleaned_daily_base WHERE 日期 >= '{cutoff_date}'"
        
        try:
            self.df = pd.read_sql(query, self.conn)
            if self.df.empty:
                print("⚠️ 2023後無數據，切換至保底模式讀取最後 10 萬筆")
                self.df = pd.read_sql("SELECT * FROM cleaned_daily_base ORDER BY 日期 DESC LIMIT 100000", self.conn)
        except Exception as e:
            print(f"⚠️ SQL 讀取錯誤: {e}")
            return f"Error: {e}"

        print(f"📊 數據量: {len(self.df)} 筆。開始精煉指標...")

        # 3. 基礎預處理
        self.df = self.df.sort_values(['StockID', '日期']).reset_index(drop=True)
        self.df['日期'] = pd.to_datetime(self.df['日期'])
        
        # 4. 套用市場規則 (漲停判定)
        self.df = self.rules.apply(self.df)
        
        # 5. 計算各項指標
        self.calculate_returns()
        self.calculate_rolling_returns()
        self.calculate_period_returns()
        self.calculate_sequence_counts()
        self.calculate_risk_metrics_extended()
        
        # 6. 轉回日期字串，準備寫入
        self.df['日期'] = self.df['日期'].dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # 7. 寫回資料庫 (這裡使用 replace 會更新表格結構，包含新欄位 Ret_High)
        print("💾 正在寫入精煉數據...")
        self.df.to_sql("cleaned_daily_base", self.conn, if_exists="replace", index=False)
        
        # 8. 壓縮檔案空間
        print("🧹 執行 VACUUM 壓縮...")
        try:
            self.conn.execute("VACUUM")
        except: pass
        
        last_date = self.df['日期'].max()
        return f"✅ {self.market_abbr} 精煉完成！最新日期：{last_date}"

    # --- 核心計算邏輯 ---
    def calculate_returns(self):
        # 計算前日收盤
        self.df['Prev_Close'] = self.df.groupby('StockID')['收盤'].shift(1)
        
        # 今日收盤漲跌幅
        self.df['Ret_Day'] = (self.df['收盤'] / self.df['Prev_Close']) - 1
        
        # 隔日溢價 (開盤漲跌幅)
        self.df['Overnight_Alpha'] = (self.df['開盤'] / self.df['Prev_Close']) - 1
        
        # 🚀 盤中最高點漲幅 (Next_1D_Max 與 Ret_High 雙存，確保 Deep_Scan.py 相容)
        self.df['Next_1D_Max'] = (self.df['最高'] / self.df['Prev_Close']) - 1
        self.df['Ret_High'] = self.df['Next_1D_Max']
        
        # 新增 Prev_LU (前日是否漲停)，用於炸板判斷
        self.df['Prev_LU'] = self.df.groupby('StockID')['is_limit_up'].shift(1).fillna(0)

    def calculate_rolling_returns(self):
        for d in [5, 20, 200]:
            self.df[f'Ret_{d}D'] = self.df.groupby('StockID')['收盤'].transform(lambda x: x / x.shift(d) - 1)

    def calculate_period_returns(self):
        temp_dt = pd.to_datetime(self.df['日期'])
        week_first = self.df.groupby(['StockID', temp_dt.dt.to_period('W')])['收盤'].transform('first')
        self.df['周累计漲跌幅(本周开盘)'] = (self.df['收盤'] / week_first) - 1
        month_first = self.df.groupby(['StockID', temp_dt.dt.to_period('M')])['收盤'].transform('first')
        self.df['月累计漲跌幅(本月开盘)'] = (self.df['收盤'] / month_first) - 1
        year_first = self.df.groupby(['StockID', temp_dt.dt.year])['收盤'].transform('first')
        self.df['年累計漲跌幅(本年开盘)'] = (self.df['收盤'] / year_first) - 1

    def calculate_sequence_counts(self):
        def get_sequence(series):
            blocks = (series != series.shift()).cumsum()
            return series * (series.groupby(blocks).cumcount() + 1)
        self.df['Seq_LU_Count'] = self.df.groupby('StockID')['is_limit_up'].transform(get_sequence)

    def calculate_risk_metrics_extended(self):
        for d in [10, 20, 50]:
            self.df[f'volatility_{d}d'] = self.df.groupby('StockID')['Ret_Day'].transform(
                lambda x: x.rolling(d).std() * (252**0.5)
            )
            rolling_max = self.df.groupby('StockID')['收盤'].transform(lambda x: x.rolling(d, min_periods=1).max())
            self.df[f'drawdown_after_high_{d}d'] = (self.df['收盤'] / rolling_max) - 1
        rolling_min_10d = self.df.groupby('StockID')['收盤'].transform(lambda x: x.rolling(10, min_periods=1).min())
        self.df['recovery_from_dd_10d'] = (self.df['收盤'] / rolling_min_10d) - 1
