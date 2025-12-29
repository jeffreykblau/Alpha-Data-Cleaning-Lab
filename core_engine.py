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
        # 你的乒乓清洗門檻
        self.PINGPONG_THRESHOLD = 0.40

    def execute(self):
        print(f"--- 🚀 啟動 {self.market_abbr} 數據精煉 ---")
        
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

        # --- [新增] A. 執行乒乓異常數據清洗 ---
        self._clean_pingpong_data()

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
        self.df = self.rules.apply(self.df)
        
        # 5. 💡 全球強勢標記邏輯
        self._apply_global_strong_event_detection()

        # 6. 計算技術指標
        self.calculate_returns()  # 此處已修改，會包含 Prev_LU
        self.calculate_rolling_returns()
        self.calculate_period_returns()
        self.calculate_sequence_counts()
        self.calculate_risk_metrics_extended()
        
        # 7. 格式化輸出
        self.df['日期'] = self.df['日期'].dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # 8. 寫入資料庫
        print(f"💾 正在更新加工表 cleaned_daily_base...")
        self.df.to_sql("cleaned_daily_base", self.conn, if_exists="replace", index=False)
        
        # 9. 優化資料庫索引 (確保 Deep_Scan 查詢飛快)
        try:
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_date ON cleaned_daily_base (StockID, 日期)")
            self.conn.execute("VACUUM")
        except:
            pass
        
        return f"✅ {self.market_abbr} 精煉完成！"

    def _clean_pingpong_data(self):
        """ 偵測並剔除極端震盪 (乒乓) 數據 """
        print("🧼 執行乒乓異常數據清洗...")
        self.df = self.df.sort_values(['StockID', '日期'])
        # 計算簡單漲跌幅用於偵測
        self.df['temp_ret'] = self.df.groupby('StockID')['收盤'].pct_change()
        
        # 標記邏輯：當日漲幅與次日跌幅皆超過門檻且方向相反
        mask_pingpong = pd.Series(False, index=self.df.index)
        groups = self.df.groupby('StockID')
        
        for name, group in groups:
            prev = group['temp_ret']
            nxt = group['temp_ret'].shift(-1)
            # 偵測前後兩日極端反向震盪
            is_bad = (prev.abs() > self.PINGPONG_THRESHOLD) & \
                     (nxt.abs() > self.PINGPONG_THRESHOLD) & \
                     (prev * nxt < 0)
            mask_pingpong.update(is_bad | is_bad.shift(1))
            
        initial_len = len(self.df)
        self.df = self.df[~mask_pingpong].copy()
        self.df.drop(columns=['temp_ret'], inplace=True)
        print(f"✨ 已剔除 {initial_len - len(self.df)} 筆異常乒乓數據。")

    def _apply_global_strong_event_detection(self):
        """ 強勢股偵測：標註 is_limit_up """
        prev_close = self.df.groupby('StockID')['收盤'].shift(1)
        ret_vs_prev = (self.df['收盤'] / prev_close) - 1
        
        # 判定漲停/強勢條件
        is_high_return = (ret_vs_prev >= 0.098)
        is_jp_limit = (self.market_abbr == "JP") & (ret_vs_prev >= 0.08) & (self.df['收盤'] == self.df['最高'])

        # 初始化並賦值
        self.df['is_limit_up'] = 0
        self.df.loc[is_high_return | is_jp_limit, 'is_limit_up'] = 1
        print(f"📊 強勢事件標註完成。")

    def calculate_returns(self):
        """ [關鍵修改] 增加 Prev_LU 與 Next_1D_Max """
        groups = self.df.groupby('StockID')
        
        self.df['Prev_Close'] = groups['收盤'].shift(1)
        self.df['Ret_Day'] = (self.df['收盤'] / self.df['Prev_Close']) - 1
        self.df['Overnight_Alpha'] = (self.df['開盤'] / self.df['Prev_Close']) - 1
        self.df['Ret_High'] = (self.df['最高'] / self.df['Prev_Close']) - 1
        
        # 解決 Deep_Scan 報錯：增加 Prev_LU (昨日是否漲停)
        self.df['Prev_LU'] = groups['is_limit_up'].shift(1).fillna(0)
        
        # 增加 Next_1D_Max (今日漲停後，隔日的最高回報) 用於 AI 診斷溢價
        self.df['Next_1D_Max'] = groups['Ret_High'].shift(-1)
