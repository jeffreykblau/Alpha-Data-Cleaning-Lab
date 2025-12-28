# -*- coding: utf-8 -*-
import pandas as pd
import numpy as np

class MarketRuleRouter:
    def __init__(self, market_type="TW"):
        self.market_type = market_type.upper()

    @classmethod
    def get_rules(cls, market_abbr):
        return cls(market_type=market_abbr)

    def apply(self, df):
        if df.empty:
            return df

        # 1. 確保排序
        df = df.sort_values(['StockID', '日期']).reset_index(drop=True)
        
        # 2. 計算前日收盤（若 core_engine 尚未計算則補上）
        if 'Prev_Close' not in df.columns:
            df['Prev_Close'] = df.groupby('StockID')['收盤'].shift(1)

        # 3. 根據市場分發規則
        if self.market_type == "TW":
            return self._apply_taiwan_rules(df)
        elif self.market_type == "US":
            return self._apply_us_rules(df)
        elif self.market_type == "CN":
            return self._apply_china_rules(df)
        elif self.market_type == "KR":
            return self._apply_korea_rules(df)
        else:
            return self._apply_generic_rules(df)

    def _apply_taiwan_rules(self, df):
        """ 台灣市場：上市櫃 10%, 興櫃標註強勢 """
        is_etf = df['StockID'].str.startswith('00')
        if 'MarketType' in df.columns:
            is_etf = is_etf | (df['MarketType'] == 'ETF')
            is_rotc = df['MarketType'].isin(['興櫃', 'ROTC'])
        else:
            is_rotc = False

        df['is_limit_up'] = 0
        # 一般上市櫃 (10% 門檻)
        mask_lu = (~is_etf) & (~is_rotc) & (df['收盤'] >= df['Prev_Close'] * 1.095)
        df.loc[mask_lu, 'is_limit_up'] = 1
        
        df['failed_lu_threshold'] = 0.095
        return df

    def _apply_us_rules(self, df):
        """ 美國市場：無限制，改為 10% (0.098) 作為強勢標記 """
        # 只要漲幅超過 9.8% 即標註為 is_limit_up (10% 門檻)
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

    def _apply_korea_rules(self, df):
        df['is_limit_up'] = (df['收盤'] >= df['Prev_Close'] * 1.295).astype(int)
        df['failed_lu_threshold'] = 0.295
        return df

    def _apply_generic_rules(self, df):
        """ 通用規則：適用於 HK 或其他市場，預設 10% 為強勢標記 """
        df['is_limit_up'] = ((df['收盤'] / df['Prev_Close'] - 1) >= 0.095).astype(int)
        df['failed_lu_threshold'] = 0.095
        return df
