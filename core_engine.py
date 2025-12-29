# -*- coding: utf-8 -*-
import pandas as pd
import numpy as np
import sqlite3
import os
from MarketRuleRouter import MarketRuleRouter

class AlphaCoreEngine:
    """
    Alpha 核心數據精煉引擎
    功能：整合多國市場規則，計算所有前端頁面所需的動能、風險、連板與預測指標。
    """
    def __init__(self, db_path, market_abbr):
        self.db_path = db_path
        self.market_abbr = market_abbr
        self.conn = sqlite3.connect(db_path)
        self.rules = MarketRuleRouter.get_rules(market_abbr)
        self.df = None

    def load_data(self):
        """ 從原始表載入數據 """
        query = "SELECT * FROM daily_stock_data"
        self.df = pd.read_sql(query, self.conn)
        self.df['日期'] = pd.to_datetime(self.df['日期'])
        return self

    def execute_full_pipeline(self):
        """ 執行完整精煉流程，確保所有頁面欄位補齊 """
        if self.df is None:
            self.load_data()

        print(f"🚀 開始精煉 {self.market_abbr} 市場數據...")

        # 1. 應用市場規則 (內含：乒乓清洗、is_limit_up 標註、failed_lu_threshold)
        self.df = self.rules.apply(self.df)

        # 2. 計算基礎回報與 Deep_Scan / Today_Limit_Up 所需的預測欄位
        self._calculate_core_returns()

        # 3. 計算連板天數 (支援 Today_Limit_Up 的 Seq_LU_Count)
        self._calculate_sequence_counts()

        # 4. 計算滾動動能與周期回報 (支援 Period_Analysis 的繁簡體命名需求)
        self._calculate_period_metrics()

        # 5. 計算風險指標 (支援 Risk_Metrics 的 Volatility 與 Drawdown)
        self._calculate_risk_metrics()

        # 6. 最終整理與存檔
        self._save_to_db()
        return f"✅ {self.market_abbr} 數據精煉完成，已存入 cleaned_daily_base。"

    def _calculate_core_returns(self):
        """ 計算基礎報酬率與隔日溢價、隔日空間 """
        self.df = self.df.sort_values(['StockID', '日期'])
        groups = self.df.groupby('StockID')

        # 今日報酬
        self.df['Ret_Day'] = (self.df['收盤'] / self.df['Prev_Close']) - 1
        # 今日盤中最高漲幅 (用來判定炸板)
        self.df['Ret_High'] = (self.df['最高'] / self.df['Prev_Close']) - 1
        # 今日隔夜溢價 (開盤相對於昨收)
        self.df['Overnight_Alpha'] = (self.df['開盤'] / self.df['Prev_Close']) - 1
        
        # 建立 Prev_LU (昨日是否漲停)
        self.df['Prev_LU'] = groups['is_limit_up'].shift(1).fillna(0)
        
        # 建立 Next_1D_Max (明日最大空間 - 供 Deep_Scan 診斷明日勝率)
        self.df['Next_1D_Max'] = groups['Ret_High'].shift(-1)
        
        # 建立 Next_1D_Ret (明日終場漲跌)
        self.df['Next_1D_Ret'] = groups['Ret_Day'].shift(-1)

    def _calculate_sequence_counts(self):
        """ 計算連續漲停天數 (Seq_LU_Count) """
        def get_seq_lu(s):
            # 透過 block 累積來區分連續區塊
            blocks = (s != s.shift()).cumsum()
            return (s == 1).astype(int) * (s.groupby(blocks).cumcount() + 1)
        
        self.df['Seq_LU_Count'] = self.df.groupby('StockID')['is_limit_up'].transform(get_seq_lu)

    def _calculate_period_metrics(self):
        """ 計算滾動報酬與特定週期報酬 (對接 Period_Analysis) """
        groups = self.df.groupby('StockID')

        # A. 滾動回報 (5D, 20D, 200D)
        for d in [5, 20, 200]:
            self.df[f'Ret_{d}D'] = groups['收盤'].transform(lambda x: x.pct_change(periods=d))

        # B. 日曆週期報酬 (採用頁面要求的特定繁簡體命名)
        # 本周累積：從本周第一個交易日至今
        self.df['周累计漲跌幅(本周开盘)'] = groups['收盤'].transform(
            lambda x: x / x.rolling(window=5, min_periods=1).apply(lambda y: y[0], raw=True) - 1
        )
        # 本月累積
        self.df['月累计漲跌幅(本月开盘)'] = groups['收盤'].transform(
            lambda x: x / x.rolling(window=20, min_periods=1).apply(lambda y: y[0], raw=True) - 1
        )
        # 本年累積
        self.df['年累計漲跌幅(本年开盘)'] = groups['收盤'].transform(
            lambda x: x / x.rolling(window=250, min_periods=1).apply(lambda y: y[0], raw=True) - 1
        )

    def _calculate_risk_metrics(self):
        """ 計算風險指標 (對接 Risk_Metrics) """
        groups = self.df.groupby('StockID')

        # 1. 滾動波動率 (Volatility - 年化標準差)
        for d in [10, 20, 50]:
            self.df[f'volatility_{d}d'] = groups['Ret_Day'].transform(
                lambda x: x.rolling(window=d).std() * np.sqrt(252)
            )

        # 2. 最大回撤 (Drawdown after High)
        # 邏輯：(今日收盤 / 近 N 日最高價) - 1
        for d in [10, 20, 50]:
            rolling_high = groups['最高'].transform(lambda x: x.rolling(window=d, min_periods=1).max())
            self.df[f'drawdown_after_high_{d}d'] = (self.df['收盤'] / rolling_high) - 1

        # 3. 恢復力 (Recovery)
        # 簡化邏輯：今日收盤相對於 10D 最低點的回升幅度
        rolling_low_10 = groups['最低'].transform(lambda x: x.rolling(window=10, min_periods=1).min())
        self.df['recovery_from_dd_10d'] = (self.df['收盤'] / rolling_low_10) - 1

    def _save_to_db(self):
        """ 儲存精煉後的數據 """
        # 轉換日期格式以便 SQLite 排序
        save_df = self.df.copy()
        save_df['日期'] = save_df['日期'].dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # 存入新表
        save_df.to_sql("cleaned_daily_base", self.conn, if_exists="replace", index=False)
        self.conn.close()

# --- 使用範例 ---
# engine = AlphaCoreEngine("tw_stock_warehouse.db", "TW")
# engine.execute_full_pipeline()
