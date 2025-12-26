# -*- coding: utf-8 -*-

class MarketRuleRouter:
    """
    國別策略路由器：根據市場縮寫將資料流導入對應的判定規則。
    """
    @staticmethod
    def get_rules(market_abbr):
        market_abbr = market_abbr.upper()
        if market_abbr == 'TW':
            return TaiwanRules()
        elif market_abbr == 'JP':
            return JapanRules()
        elif market_abbr == 'CN':
            return ChinaRules()
        # 美國 (US)、香港 (HK)、韓國 (KR) 統一由 BaseRules 的 10% 邏輯處理
        return BaseRules()

class BaseRules:
    """
    基礎規則類別：適用於 US, HK, KR 等無嚴格漲停限制市場。
    定義單日漲幅 ≥ 10% 且收紅K為「強勢標的」。
    """
    def classify_lu_type4(self, row, limit_price):
        # 1:無量鎖死, 2:跳空, 3:爆量, 4:普通
        if row.get('開盤') >= limit_price - 0.01 and row.get('最高') == row.get('最低'): return 1
        if (row.get('開盤') / row.get('PrevClose', 1) - 1) >= 0.07: return 2
        if row.get('Vol_Ratio', 0) >= 3.0: return 3
        return 4

    def classify_fail_type(self, row):
        # 1:崩潰(Fail1), 2:炸板(Fail2), 4:無溢價
        if row.get('Ret_Day', 0) <= -0.05: return 1
        # 盤中觸及過 Limit_Price 但最後沒收在上面
        if row.get('最高', 0) >= row.get('Limit_Price', 999999) and not row.get('is_limit_up', False): return 2
        if row.get('Overnight_Alpha', 0) <= 0: return 4
        return 0

    def apply(self, df):
        """通用 10% 強勢股判定邏輯"""
        # 統一計算昨收的 1.1 倍作為參考漲停價
        df['Limit_Price'] = df['PrevClose'] * 1.1 
        # 判定條件：漲幅 >= 10% 且當天是收紅 K (收盤 >= 開盤)
        df['is_limit_up'] = (df['Ret_Day'] >= 0.10) & (df['收盤'] >= df['開盤'])
        df['is_limit_down'] = df['Ret_Day'] <= -0.10
        # 異常值過濾：無限制市場設為 100% 波動
        df['is_anomaly'] = df['Ret_Day'].abs() > 1.0 
        return df

class TaiwanRules(BaseRules):
    """
    台股規則：區分上市櫃 10% 與 興櫃標記。
    """
    def apply(self, df):
        df['Limit_Price'] = (df['PrevClose'] * 1.1).round(2)
        # 判斷市場別，若無標籤則預設為 10%
        if 'MarketType' in df.columns:
            listed = df['MarketType'].isin(['上市', '上櫃'])
            df.loc[listed, 'is_limit_up'] = df['Ret_Day'] >= 0.095
            df.loc[listed, 'is_limit_down'] = df['Ret_Day'] <= -0.095
            
            # 興櫃市場不標記漲停，僅標記異常
            emg = df['MarketType'] == '興櫃'
            df.loc[emg, 'is_limit_up'] = False
        else:
            df['is_limit_up'] = df['Ret_Day'] >= 0.095
            df['is_limit_down'] = df['Ret_Day'] <= -0.095

        df['is_anomaly'] = df['Ret_Day'].abs() > 0.11
        return df

class JapanRules(BaseRules):
    """
    日股規則：採用交易所固定金額(Tick)漲停制。
    """
    def apply(self, df):
        def get_jp_limit(p):
            if p < 100: return 30
            if p < 500: return 80
            if p < 1000: return 150
            if p < 1500: return 300
            if p < 3000: return 500
            if p < 5000: return 700
            return 1000
            
        df['JP_Limit_Amt'] = df['PrevClose'].apply(get_jp_limit)
        df['Limit_Price'] = df['PrevClose'] + df['JP_Limit_Amt']
        # 日股收盤價達到或超過預設漲停價（考慮1單位誤差）即視為漲停
        df['is_limit_up'] = df['收盤'] >= (df['Limit_Price'] - 1)
        df['is_limit_down'] = False 
        df['is_anomaly'] = df['Ret_Day'].abs() > 0.5
        return df

class ChinaRules(BaseRules):
    """
    陸股規則：簡化判定主板 10%。
    """
    def apply(self, df):
        df['Limit_Price'] = (df['PrevClose'] * 1.1).round(2)
        # 中國 A 股通常以 9.5% 作為漲停門檻
        df['is_limit_up'] = df['Ret_Day'] >= 0.095
        df['is_limit_down'] = df['Ret_Day'] <= -0.095
        df['is_anomaly'] = df['Ret_Day'].abs() > 0.22
        return df
