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
        print(f"--- 🚀 啟動 {self.market_abbr} 數據精煉 (修正 12/26 斷層版) ---")
        
        # 1. 💡 關鍵修正：直接從原始股價表 (stock_prices) 讀取原料
        # 我們讀取 2023 年以後的所有原始 K 線數據
        query = """
            SELECT date as 日期, symbol as StockID, open as 開盤, 
                   high as 最高, low as 最低, close as 收盤, volume as 成交量
            FROM stock_prices 
            WHERE date >= '2023-01-01'
        """
        
        try:
            self.df = pd.read_sql(query, self.conn)
            if self.df.empty:
                print(f"❌ {self.market_abbr} 原始表 stock_prices 無數據，請先檢查下載腳本。")
                return "Error: No raw data found"
        except Exception as e:
            print(f"⚠️ 讀取原始數據失敗: {e}")
            return f"Error: {e}"

        print(f"📊 讀入原始數據量: {len(self.df)} 筆。")

        # 2. 基礎預處理
        self.df = self.df.sort_values(['StockID', '日期']).reset_index(drop=True)
        self.df['日期'] = pd.to_datetime(self.df['日期'])
        
        # 3. 💡 整合市場別資訊 (用於興櫃判定)
        try:
            # 從 stock_info 抓取市場別 (MarketType) 和名稱 (stock_name)
            info_df = pd.read_sql("SELECT symbol as StockID, market as MarketType, name as stock_name FROM stock_info", self.conn)
            self.df = pd.merge(self.df, info_df, on='StockID', how='left')
        except Exception as e:
            print(f"⚠️ 無法取得市場資訊: {e}，將使用通用漲跌幅規則。")
            self.df['MarketType'] = 'Unknown'
            self.df['stock_name'] = 'Unknown'

        # 4. 套用市場規則 (漲停/跌停/產業規則)
        # 這裡會根據你傳入的 rules 計算基礎的 is_limit_up, is_limit_down
        self.df = self.rules.apply(self.df)
        
        # 5. 💡 針對興櫃市場 (ROTC) 的 10% 強勢標記
        self._apply_market_type_adjustments()

        # 6. 計算各項技術指標與報酬率
        self.calculate_returns()
        self.calculate_rolling_returns()
        self.calculate_period_returns()
        self.calculate_sequence_counts()
        self.calculate_risk_metrics_extended()
        
        # 7. 數據清洗與輸出格式化
        # 在寫入前將日期轉回字串格式 (SQLite 對字串排序最穩定)
        self.df['日期'] = self.df['日期'].dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # 8. 💡 覆蓋寫入加工表
        print(f"💾 正在更新加工表 cleaned_daily_base (共 {len(self.df)} 筆)...")
        # 使用 if_exists='replace' 確保結構更新 (如新增的 MarketType 欄位)
        self.df.to_sql("cleaned_daily_base", self.conn, if_exists="replace", index=False)
        
        # 9. 維護資料庫效能
        print("🧹 執行資料庫 VACUUM 壓縮...")
        try:
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_date ON cleaned_daily_base (StockID, 日期)")
            self.conn.execute("VACUUM")
        except:
            pass
        
        max_date = self.df['日期'].max()
        return f"✅ {self.market_abbr} 精煉成功！最新日期已更新至：{max_date}"

    # --- 內部增強邏輯 ---

    def _apply_market_type_adjustments(self):
        """
        處理興櫃市場 (ROTC/興櫃) 的特殊強度標記
        由於興櫃無漲跌幅限制，我們將 > 10% 視為強勢標的 (is_limit_up = 1)
        """
        if 'MarketType' not in self.df.columns:
            return

        # 計算今日漲幅
        prev_close = self.df.groupby('StockID')['收盤'].shift(1)
        ret_temp = (self.df['收盤'] / prev_close) - 1

        # 判定興櫃強勢股
        is_rotc = self.df['MarketType'].isin(['興櫃', 'ROTC'])
        
        # 1. 標記興櫃且漲幅超過 10% 的股票為強勢 (is_rotc_strong)
        self.df['is_rotc_strong'] = (is_rotc & (ret_temp >= 0.1)).astype(int)
        
        # 2. 💡 強制讓興櫃強勢股出現在「漲停篩選」中 (讓 is_limit_up = 1)
        # 這樣你的 1000 日新高篩選器就能抓到這些興櫃飆股
        self.df.loc[is_rotc & (ret_temp >= 0.1), 'is_limit_up'] = 1
        
        print(f"📊 興櫃處理：已標註 {(self.df['is_rotc_strong']==1).sum()} 筆 10% 以上強勢事件。")

    def calculate_returns(self):
        """計算基礎報酬率與最高價漲幅"""
        self.df['Prev_Close'] = self.df.groupby('StockID')['收盤'].shift(1)
        
        # 今日收盤漲跌幅
        self.df['Ret_Day'] = (self.df['收盤'] / self.df['Prev_Close']) - 1
        
        # 隔日溢價 (開盤相對於前日收盤)
        self.df['Overnight_Alpha'] = (self.df['開盤'] / self.df['Prev_Close']) - 1
        
        # 🚀 盤中最高點漲幅 (對應你篩選器需要的 Ret_High)
        self.df['Ret_High'] = (self.df['最高'] / self.df['Prev_Close']) - 1
        self.df['Next_1D_Max'] = self.df['Ret_High'] # 雙存以確保相容
        
        # 前日是否漲停標記
        self.df['Prev_LU'] = self.df.groupby('StockID')['is_limit_up'].shift(1).fillna(0)

    def calculate_rolling_returns(self):
        """計算滾動週期報酬 (5日, 20日, 200日)"""
        for d in [5, 20, 200]:
            self.df[f'Ret_{d}D'] = self.df.groupby('StockID')['收盤'].transform(lambda x: x / x.shift(d) - 1)

    def calculate_period_returns(self):
        """計算週、月、年累積漲跌幅"""
        temp_dt = pd.to_datetime(self.df['日期'])
        week_first = self.df.groupby(['StockID', temp_dt.dt.to_period('W')])['收盤'].transform('first')
        self.df['周累计漲跌幅(本周开盘)'] = (self.df['收盤'] / week_first) - 1
        
        month_first = self.df.groupby(['StockID', temp_dt.dt.to_period('M')])['收盤'].transform('first')
        self.df['月累计漲跌幅(本月开盘)'] = (self.df['收盤'] / month_first) - 1
        
        year_first = self.df.groupby(['StockID', temp_dt.dt.year])['收盤'].transform('first')
        self.df['年累計漲跌幅(本年开盘)'] = (self.df['收盤'] / year_first) - 1

    def calculate_sequence_counts(self):
        """計算連續漲停天數"""
        def get_sequence(series):
            blocks = (series != series.shift()).cumsum()
            return series * (series.groupby(blocks).cumcount() + 1)
        self.df['Seq_LU_Count'] = self.df.groupby('StockID')['is_limit_up'].transform(get_sequence)

    def calculate_risk_metrics_extended(self):
        """計算波動率與回檔指標 (10, 20, 50日)"""
        for d in [10, 20, 50]:
            # 年化波動率
            self.df[f'volatility_{d}d'] = self.df.groupby('StockID')['Ret_Day'].transform(
                lambda x: x.rolling(d).std() * (252**0.5)
            )
            # 區間高點回檔幅
            rolling_max = self.df.groupby('StockID')['收盤'].transform(lambda x: x.rolling(d, min_periods=1).max())
            self.df[f'drawdown_after_high_{d}d'] = (self.df['收盤'] / rolling_max) - 1
            
        # 從 10 日低點的反彈幅
        rolling_min_10d = self.df.groupby('StockID')['收盤'].transform(lambda x: x.rolling(10, min_periods=1).min())
        self.df['recovery_from_dd_10d'] = (self.df['收盤'] / rolling_min_10d) - 1
