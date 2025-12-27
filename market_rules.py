import pandas as pd

class MarketRuleRouter:
    def __init__(self, market_type="TW"):
        self.market_type = market_type.upper()

    @classmethod
    def get_rules(cls, market_abbr):
        """
        供 main_pipeline.py 呼叫的類別方法
        """
        return cls(market_type=market_abbr)

    def apply(self, df):
        """
        執行漲停判定與炸板門檻標記邏輯
        """
        if df.empty:
            return df

        # 1. 確保排序以計算前日收盤
        df = df.sort_values(['StockID', '日期']).reset_index(drop=True)
        df['Prev_Close'] = df.groupby('StockID')['收盤'].shift(1)

        # 2. 根據市場分發規則 (包含 is_limit_up 與 failed_lu_threshold)
        if self.market_type == "TW":
            return self._apply_taiwan_rules(df)
        elif self.market_type == "US":
            return self._apply_us_rules(df)
        elif self.market_type == "CN":
            return self._apply_china_rules(df)
        else:
            return self._apply_generic_rules(df)

    def _apply_taiwan_rules(self, df):
        """
        台灣市場：10% 漲停限制 (ETF 除外)
        """
        sector_col = '產業' if '產業' in df.columns else 'Sector'
        is_etf = df['StockID'].str.startswith('00')
        if sector_col in df.columns:
            is_etf = is_etf | df[sector_col].isna()
        
        df['is_limit_up'] = 0
        # 判定基準：今日收盤 >= 昨日收盤 * 1.095 (且非 ETF)
        mask_lu = (~is_etf) & (df['收盤'] >= df['Prev_Close'] * 1.095)
        df.loc[mask_lu, 'is_limit_up'] = 1
        
        # 炸板門檻：9.5%
        df['failed_lu_threshold'] = 0.095
        return df

    def _apply_us_rules(self, df):
        """
        美國市場：無漲停限制，自定義強勢門檻 15%
        """
        df['is_limit_up'] = ((df['收盤'] / df['Prev_Close'] - 1) >= 0.15).astype(int)
        # 炸板門檻：14% (美股波動大，自定義較高門檻)
        df['failed_lu_threshold'] = 0.14
        return df

    def _apply_china_rules(self, df):
        """
        中國市場：主板 10%, 創/科 20%
        """
        # 判定 A 股 20% 限制 (代碼 30 或 68 開頭)
        is_20pct = df['StockID'].str.startswith(('30', '68'))
        
        df['is_limit_up'] = 0
        # 20% 漲停判定
        mask_20 = is_20pct & (df['收盤'] >= df['Prev_Close'] * 1.195)
        # 10% 漲停判定
        mask_10 = (~is_20pct) & (df['收盤'] >= df['Prev_Close'] * 1.095)
        
        df.loc[mask_20 | mask_10, 'is_limit_up'] = 1
        
        # 動態設定炸板門檻
        df['failed_lu_threshold'] = 0.095
        df.loc[is_20pct, 'failed_lu_threshold'] = 0.195
        return df

    def _apply_generic_rules(self, df):
        """
        通用規則 (日/韓/港) 暫採 9.5% 門檻
        """
        df['is_limit_up'] = ((df['收盤'] / df['Prev_Close'] - 1) >= 0.095).astype(int)
        df['failed_lu_threshold'] = 0.095
        return df
