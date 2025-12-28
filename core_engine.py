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
        
        # 1. 讀取原始數據 (確保從 2023 開始，資料庫更精簡)
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

        # 4. 套用基礎市場規則 (由各國 Rules 物件定義)
        # 即使 rules 沒抓到，後續的 global 偵測也會補強
        self.df = self.rules.apply(self.df)
        
        # 5. 💡 全球強勢標記邏輯 (取代原本的台灣專屬邏輯)
        self._apply_global_strong_event_detection()

        # 6. 計算技術指標
        self.calculate_returns()
        self.calculate_rolling_returns()
        self.calculate_period_returns()
        self.calculate_sequence_counts()
        self.calculate_risk_metrics_extended()
        
        # 7. 格式化輸出
        self.df['日期'] = self.df['日期'].dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # 8. 寫入資料庫 (加工表 cleaned_daily_base)
        print(f"💾 正在更新加工表 cleaned_daily_base...")
        self.df.to_sql("cleaned_daily_base", self.conn, if_exists="replace", index=False)
        
        # 9. 優化資料庫索引
        try:
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_date ON cleaned_daily_base (StockID, 日期)")
            self.conn.execute("VACUUM")
        except:
            pass
        
        return f"✅ {self.market_abbr} 精煉完成！"

    def _apply_global_strong_event_detection(self):
        """ 
        全球強勢股偵測補強：
        不論哪國市場，只要漲幅 > 10% 或符合特定強勢條件，皆標註為 is_limit_up = 1
        """
        # 計算漲幅與日內實體
        prev_close = self.df.groupby('StockID')['收盤'].shift(1)
        ret_vs_prev = (self.df['收盤'] / prev_close) - 1
        ret_intraday = (self.df['收盤'] / self.df['開盤']) - 1 

        # --- 定義判定門檻 ---
        
        # 1. 通用門檻：漲幅 >= 9.8% (包含台/陸漲停、美/韓大漲)
        is_high_return = (ret_vs_prev >= 0.098)
        
        # 2. 實體紅棒門檻：當日開盤到收盤漲幅 >= 9.8% (針對無漲幅限制市場，捕捉盤中噴發)
        is_solid_red = (ret_intraday >= 0.098)

        # 3. 日本(JP)特化：漲幅 >= 8% 且收在當日最高 (捕捉階梯式漲停鎖死)
        is_jp_limit = (self.market_abbr == "JP") & (ret_vs_prev >= 0.08) & (self.df['收盤'] == self.df['最高'])

        # 綜合判定
        strong_condition = is_high_return | is_solid_red | is_jp_limit
        
        # 執行更新
        self.df.loc[strong_condition, 'is_limit_up'] = 1
        
        # 日誌統計
        count = self.df[strong_condition].shape[0]
        print(f"📊 {self.market_abbr} 強勢偵測：已標註 {count} 筆強勢事件 (漲幅 > 10% 或特化規則)。")

    def calculate_returns(self):
        self.df['Prev_Close'] = self.df.groupby('StockID')['收盤'].shift(1)
        self.df['Ret_Day'] = (self.df['收盤'] / self.df['Prev_Close']) - 1
        self.df['Overnight_Alpha'] = (self.df['開盤'] / self.df['Prev_Close']) - 1
        self.df['Ret_High'] = (self.df['最高'] / self.df['Prev_Close']) - 1
        
    def calculate_rolling_returns(self):
        for d in [5, 20, 200]:
            # 修正 transform 寫法確保穩定
            self.df[f'Ret_{d}D'] = self.df.groupby('StockID')['收盤'].transform(lambda x: x / x.shift(d) - 1)

    def calculate_period_returns(self):
        temp_dt = pd.to_datetime(self.df['日期'])
        for p, label in [('W', '周'), ('M', '月')]:
            # 使用 temp_dt 避免修改原始 dataframe 格式
            first = self.df.groupby(['StockID', temp_dt.dt.to_period(p)])['收盤'].transform('first')
            self.df[f'{label}累计漲跌幅'] = (self.df['收盤'] / first) - 1

    def calculate_sequence_counts(self):
        """ 修正連漲/連跌計數邏輯 """
        def get_sequence(series):
            # 只要 series 不為 0 且連續，就開始計數
            blocks = (series != series.shift()).cumsum()
            return series * (series.groupby(blocks).cumcount() + 1)
        
        # Seq_LU_Count 代表「連續強勢/漲停天數」
        self.df['Seq_LU_Count'] = self.df.groupby('StockID')['is_limit_up'].transform(get_sequence)

    def calculate_risk_metrics_extended(self):
        for d in [10, 20]:
            self.df[f'volatility_{d}d'] = self.df.groupby('StockID')['Ret_Day'].transform(
                lambda x: x.rolling(d).std() * (252**0.5)
            )
