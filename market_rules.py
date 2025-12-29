# -*- coding: utf-8 -*-
import pandas as pd
import numpy as np

class MarketRuleRouter:
    """
    市場規則路由：負責數據清洗、各國漲停板判定、以及異常值剔除。
    此版本整合了：
    1. 乒乓清洗 (Ping-pong Cleaning): 剔除減資、除權息錯誤等 40% 以上的極端數據。
    2. 多國漲停門檻: 支援台、美、中、日、港、韓。
    3. 炸板門檻設定: 支援 AI 診斷所需的 failed_lu_threshold。
    """

    def __init__(self, market_type="TW"):
        self.market_type = market_type.upper()
        # 設置 40% 為乒乓清洗門檻，這只會剔除數據異常，絕對不會刪到 10% 的漲停板
        self.PINGPONG_THRESHOLD = 0.40

    @classmethod
    def get_rules(cls, market_abbr):
        return cls(market_type=market_abbr)

    def apply(self, df):
        """ 執行完整清洗與規則應用流程 """
        if df.empty:
            return df

        # 1. 確保數據基礎排序
        df = df.sort_values(['StockID', '日期']).reset_index(drop=True)
        
        # 2. 建立基礎價格欄位 (若 core_engine 尚未計算則補上)
        if 'Prev_Close' not in df.columns:
            df['Prev_Close'] = df.groupby('StockID')['收盤'].shift(1)

        # 3. 🚨 執行【乒乓異常數據清洗】 (防止數據污染 AI 診斷)
        df = self._clean_pingpong_data(df)

        # 4. 根據市場分發規則 (計算 is_limit_up 與 failed_lu_threshold)
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
        """ 專業清洗：剔除極端異常震盪 (如未還原的減資) """
        # 計算臨時漲跌幅
        df['temp_ret'] = (df['收盤'] / df['Prev_Close']) - 1
        
        # 偵測條件：當日漲跌 > 40% 且 次日漲跌 > 40% 且 方向相反 (乒乓效應)
        prev_ret = df['temp_ret']
        next_ret = df.groupby('StockID')['temp_ret'].shift(-1)
        
        mask_pingpong = (prev_ret.abs() > self.PINGPONG_THRESHOLD) & \
                        (next_ret.abs() > self.PINGPONG_THRESHOLD) & \
                        (prev_ret * next_ret < 0)
        
        # 剔除受污染的數據點
        initial_count = len(df)
        df = df[~mask_pingpong].copy()
        
        df.drop(columns=['temp_ret'], inplace=True)
        # 註：這只會刪除極少數的異常跳空，不會影響正常交易數據
        return df

    def _apply_taiwan_rules(self, df):
        """ 台灣市場：上市櫃 10%, 興櫃標註強勢 """
        is_etf = df['StockID'].str.startswith('00')
        if 'MarketType' in df.columns:
            is_etf = is_etf | (df['MarketType'] == 'ETF')
            is_rotc = df['MarketType'].isin(['興櫃', 'ROTC'])
        else:
            is_rotc = False

        # 判定漲停 (10% 門檻)
        df['is_limit_up'] = 0
        mask_lu = (~is_etf) & (~is_rotc) & (df['收盤'] >= df['Prev_Close'] * 1.095)
        df.loc[mask_lu, 'is_limit_up'] = 1
        
        # 設定炸板判定門檻 (提供給 Deep_Scan 使用)
        df['failed_lu_threshold'] = 0.095
        return df

    def _apply_us_rules(self, df):
        """ 美國市場：無漲停限制，以 10% 作為強勢標記 """
        df['is_limit_up'] = ((df['收盤'] / df['Prev_Close'] - 1) >= 0.098).astype(int)
        df['failed_lu_threshold'] = 0.095
        return df

    def _apply_china_rules(self, df):
        """ 中國市場：主板 10%, 創/科 20% """
        is_20pct = df['StockID'].str.startswith(('30', '68'))
        df['is_limit_up'] = 0
        mask_20 = is_20pct & (df['收盤'] >= df['Prev_Close'] * 1.195)
        mask_10 = (~is_20pct) & (df['收盤'] >= df['Prev_Close'] * 1.095)
        df.loc[mask_20 | mask_10, 'is_limit_up'] = 1
        
        df['failed_lu_threshold'] = 0.095
        df.loc[is_20pct, 'failed_lu_threshold'] = 0.195
        return df

    def _apply_japan_rules(self, df):
        """ 日本市場：根據漲幅與最高價判定 """
        # 日本通常以漲幅 > 8% 且收在最高作為強勢特徵
        df['is_limit_up'] = ((df['收盤'] / df['Prev_Close'] - 1 >= 0.08) & (df['收盤'] == df['最高'])).astype(int)
        df['failed_lu_threshold'] = 0.075
        return df

    def _apply_korea_rules(self, df):
        """ 韓國市場：30% 限制 """
        df['is_limit_up'] = (df['收盤'] >= df['Prev_Close'] * 1.295).astype(int)
        df['failed_lu_threshold'] = 0.295
        return df

    def _apply_generic_rules(self, df):
        """ 通用規則：適用於 HK 或其他市場，預設 9.5% 為強勢標記 """
        df['is_limit_up'] = ((df['收盤'] / df['Prev_Close'] - 1) >= 0.095).astype(int)
        df['failed_lu_threshold'] = 0.095
        return df
