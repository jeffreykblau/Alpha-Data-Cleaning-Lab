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
        """
        台灣市場：
        - 上市/上櫃：10% 限制
        - 興櫃：無限制 (標註強勢門檻)
        - ETF：無限制
        """
        # 判定是否為 ETF (代碼 00 開頭或市場別標註)
        is_etf = df['StockID'].str.startswith('00')
        if 'MarketType' in df.columns:
            is_etf = is_etf | (df['MarketType'] == 'ETF')
            is_rotc = df['MarketType'].isin(['興櫃', 'ROTC'])
        else:
            is_rotc = False # 若無資訊則預設不處理興櫃

        df['is_limit_up'] = 0
        
        # A. 一般上市櫃漲停判定 (10% 門檻)
        # 使用 1.095 避開除權息或計算誤差
        mask_lu = (~is_etf) & (~is_rotc) & (df['收盤'] >= df['Prev_Close'] * 1.095)
        df.loc[mask_lu, 'is_limit_up'] = 1
        
        # B. 興櫃強勢判定 (自定義 10% 為強勢標記，因為興櫃沒漲停)
        # 注意：這部分在 core_engine 也有做，這裡做雙重保險
        mask_rotc_strong = is_rotc & (df['收盤'] >= df['Prev_Close'] * 1.10)
        df.loc[mask_rotc_strong, 'is_limit_up'] = 1
        
        # 設定炸板門檻標籤
        df['failed_lu_threshold'] = 0.095
        if 'MarketType' in df.columns:
            # 興櫃與 ETF 門檻調高，避免誤報
            df.loc[is_rotc | is_etf, 'failed_lu_threshold'] = 0.15 
            
        return df

    def _apply_us_rules(self, df):
        """ 美國市場：無限制，15% 為強勢標記 """
        df['is_limit_up'] = ((df['收盤'] / df['Prev_Close'] - 1) >= 0.15).astype(int)
        df['failed_lu_threshold'] = 0.14
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
        """ 韓國市場：漲跌幅限制 30% """
        # 韓國自 2015 年起漲停限制為 30%
        df['is_limit_up'] = (df['收盤'] >= df['Prev_Close'] * 1.295).astype(int)
        df['failed_lu_threshold'] = 0.295
        return df

    def _apply_generic_rules(self, df):
        """ 通用規則 """
        df['is_limit_up'] = ((df['收盤'] / df['Prev_Close'] - 1) >= 0.095).astype(int)
        df['failed_lu_threshold'] = 0.095
        return df
