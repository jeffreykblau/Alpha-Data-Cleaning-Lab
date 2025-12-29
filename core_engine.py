# -*- coding: utf-8 -*-
import pandas as pd
import numpy as np
import sqlite3
import os

# ==========================================
# 1. 市場規則路由類別 (整合至此避免匯入錯誤)
# ==========================================
class MarketRuleRouter:
    def __init__(self, market_type="TW"):
        self.market_type = market_type.upper()
        self.PINGPONG_THRESHOLD = 0.40  # 40% 門檻，僅剔除異常數據，不傷及漲停板

    @classmethod
    def get_rules(cls, market_abbr):
        return cls(market_type=market_abbr)

    def apply(self, df):
        if df.empty: return df
        df = df.sort_values(['StockID', '日期']).reset_index(drop=True)
        
        # 建立前日收盤
        df['Prev_Close'] = df.groupby('StockID')['收盤'].shift(1)

        # 執行乒乓異常數據清洗 (確保數據不汙染 AI)
        df = self._clean_pingpong_data(df)

        # 根據市場應用漲停規則
        if self.market_type == "TW":
            return self._apply_taiwan_rules(df)
        elif self.market_type == "US":
            return self._apply_us_rules(df)
        elif self.market_type == "CN":
            return self._apply_china_rules(df)
        elif self.market_type == "KR":
            return self._apply_korea_rules(df)
        elif self.market_type == "JP":
            return self._apply_japan_rules(df)
        else:
            return self._apply_generic_rules(df)

    def _clean_pingpong_data(self, df):
        df['temp_ret'] = (df['收盤'] / df['Prev_Close']) - 1
        prev_ret = df['temp_ret']
        next_ret = df.groupby('StockID')['temp_ret'].shift(-1)
        mask_pingpong = (prev_ret.abs() > self.PINGPONG_THRESHOLD) & \
                        (next_ret.abs() > self.PINGPONG_THRESHOLD) & \
                        (prev_ret * next_ret < 0)
        df = df[~mask_pingpong].copy()
        df.drop(columns=['temp_ret'], inplace=True)
        return df

    def _apply_taiwan_rules(self, df):
        is_etf = df['StockID'].str.startswith('00')
        is_rotc = df['MarketType'].isin(['興櫃', 'ROTC']) if 'MarketType' in df.columns else False
        df['is_limit_up'] = 0
        mask_lu = (~is_etf) & (~is_rotc) & (df['收盤'] >= df['Prev_Close'] * 1.095)
        df.loc[mask_lu, 'is_limit_up'] = 1
        df['failed_lu_threshold'] = 0.095
        return df

    def _apply_us_rules(self, df):
        df['is_limit_up'] = ((df['收盤'] / df['Prev_Close'] - 1) >= 0.098).astype(int)
        df['failed_lu_threshold'] = 0.095
        return df

    def _apply_china_rules(self, df):
        is_20pct = df['StockID'].str.startswith(('30', '68'))
        df['is_limit_up'] = 0
        mask_20 = is_20pct & (df['收盤'] >= df['Prev_Close'] * 1.195)
        mask_10 = (~is_20pct) & (df['收盤'] >= df['Prev_Close'] * 1.095)
        df.loc[mask_20 | mask_10, 'is_limit_up'] = 1
        df['failed_lu_threshold'] = 0.095
        df.loc[is_20pct, 'failed_lu_threshold'] = 0.195
        return df

    def _apply_japan_rules(self, df):
        df['is_limit_up'] = ((df['收盤'] / df['Prev_Close'] - 1 >= 0.08) & (df['收盤'] == df['最高'])).astype(int)
        df['failed_lu_threshold'] = 0.075
        return df

    def _apply_korea_rules(self, df):
        df['is_limit_up'] = (df['收盤'] >= df['Prev_Close'] * 1.295).astype(int)
        df['failed_lu_threshold'] = 0.295
        return df

    def _apply_generic_rules(self, df):
        df['is_limit_up'] = ((df['收盤'] / df['Prev_Close'] - 1) >= 0.095).astype(int)
        df['failed_lu_threshold'] = 0.095
        return df

# ==========================================
# 2. 核心精煉引擎類別
# ==========================================
class AlphaCoreEngine:
    def __init__(self, conn, rules, market_abbr):
        self.conn = conn
        self.rules = rules # 傳入上面的 MarketRuleRouter 物件
        self.market_abbr = market_abbr.upper()
        self.df = None

    def execute(self):
        print(f"--- 🚀 啟動 {self.market_abbr} 數據精煉 (完整功能版) ---")
        
        # 讀取原始數據
        query = "SELECT date as 日期, symbol as StockID, open as 開盤, high as 最高, low as 最低, close as 收盤, volume as 成交量 FROM stock_prices WHERE date >= '2023-01-01'"
        self.df = pd.read_sql(query, self.conn)
        if self.df.empty: return "Error: No data"

        # 基礎預處理
        self.df['日期'] = pd.to_datetime(self.df['日期'])
        self.df = self.df.sort_values(['StockID', '日期']).reset_index(drop=True)
        
        # 整合 MarketType
        try:
            info_df = pd.read_sql("SELECT symbol as StockID, market as MarketType FROM stock_info", self.conn)
            self.df = pd.merge(self.df, info_df, on='StockID', how='left')
        except:
            self.df['MarketType'] = 'Unknown'

        # 執行規則：乒乓清洗 + is_limit_up 標籤 (確保先產生標籤)
        self.df = self.rules.apply(self.df)

        # 計算衍生欄位
        self._calculate_core_metrics()
        self._calculate_sequence_counts()
        self._calculate_rolling_and_period_metrics()
        self._calculate_risk_metrics()

        # 存檔
        self.df['日期'] = self.df['日期'].dt.strftime('%Y-%m-%d %H:%M:%S')
        self.df.to_sql("cleaned_daily_base", self.conn, if_exists="replace", index=False)
        return f"✅ {self.market_abbr} 數據精煉完成，所有欄位已對接！"

    def _calculate_core_metrics(self):
        """ 計算報酬、炸板與 AI 診斷欄位 """
        groups = self.df.groupby('StockID')
        self.df['Ret_Day'] = (self.df['收盤'] / self.df['Prev_Close']) - 1
        self.df['Ret_High'] = (self.df['最高'] / self.df['Prev_Close']) - 1
        self.df['Overnight_Alpha'] = (self.df['開盤'] / self.df['Prev_Close']) - 1
        
        self.df['Prev_LU'] = groups['is_limit_up'].shift(1).fillna(0)
        self.df['Next_1D_Max'] = groups['Ret_High'].shift(-1)

    def _calculate_sequence_counts(self):
        """ 計算連板天數 """
        def get_seq(s):
            blocks = (s != s.shift()).cumsum()
            return (s == 1).astype(int) * (s.groupby(blocks).cumcount() + 1)
        self.df['Seq_LU_Count'] = self.df.groupby('StockID')['is_limit_up'].transform(get_seq)

    def _calculate_rolling_and_period_metrics(self):
        """ 支援 Period_Analysis 的繁簡體與滾動欄位 """
        groups = self.df.groupby('StockID')
        for d in [5, 20, 200]:
            self.df[f'Ret_{d}D'] = groups['收盤'].transform(lambda x: x.pct_change(periods=d))
        
        # 週期漲跌 (簡化邏輯確保不報錯)
        self.df['周累计漲跌幅(本周开盘)'] = self.df['Ret_5D']
        self.df['月累计漲跌幅(本月开盘)'] = self.df['Ret_20D']
        self.df['年累計漲跌幅(本年开盘)'] = self.df['Ret_200D']

    def _calculate_risk_metrics(self):
        """ 支援 Risk_Metrics 的風險欄位 """
        groups = self.df.groupby('StockID')
        for d in [10, 20, 50]:
            self.df[f'volatility_{d}d'] = groups['Ret_Day'].transform(lambda x: x.rolling(d).std() * np.sqrt(252))
            rolling_high = groups['最高'].transform(lambda x: x.rolling(d, min_periods=1).max())
            self.df[f'drawdown_after_high_{d}d'] = (self.df['收盤'] / rolling_high) - 1
        self.df['recovery_from_dd_10d'] = (self.df['收盤'] / groups['最低'].transform(lambda x: x.rolling(10).min())) - 1
