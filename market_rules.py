import pandas as pd

def apply_market_rules(df, market_type="TW"):
    """
    根據不同市場規則判定漲停板 (is_limit_up)
    """
    if df.empty:
        return df

    # 確保資料按日期排序，這是計算前日收盤的前提
    df = df.sort_values(['StockID', '日期'])
    
    # 核心邏輯：計算前一日收盤價 (Prev_Close)
    df['Prev_Close'] = df.groupby('StockID')['收盤'].shift(1)

    if market_type == "TW":
        # --- 台灣市場規則 ---
        
        # 1. 判定是否為 ETF (代碼 00 開頭 且 產業為 nan 或 無)
        # 台灣 ETF 通常沒有 10% 漲跌限制，應排除或放寬
        is_etf = df['StockID'].str.startswith('00')
        
        # 2. 漲停判定邏輯 (優化版)
        # 使用 1.09 是為了容錯 (因為四捨五入)，
        # 實務上台股漲停是 (昨日收盤 * 1.1) 後無條件捨去至檔位
        # 這裡用你的建議：昨日收盤 * 1.09 < 今日收盤
        df['is_limit_up'] = 0
        
        # 僅針對「非 ETF」的股票執行 9% 漲停判定
        df.loc[(~is_etf) & (df['收盤'] >= df['Prev_Close'] * 1.09), 'is_limit_up'] = 1
        
        # 針對「ETF」：除非漲幅超過 15% 否則不輕易標記為漲停 (或直接設為 0)
        df.loc[is_etf, 'is_limit_up'] = 0

    elif market_type == "US":
        # --- 美股市場規則 (統計學異常 Z-Score) ---
        # 美股無漲跌停，判定為當日漲幅 > 15% 且成交量異常
        df['is_limit_up'] = ((df['收盤'] / df['Prev_Close'] - 1) >= 0.15).astype(int)

    # 這裡可以持續擴充 JP, CN, KR 等規則
    
    return df

def get_market_logic(symbol):
    """
    根據代碼後綴判斷市場類型
    """
    if symbol.endswith(".TW") or symbol.endswith(".TWO"):
        return "TW"
    elif ".US" in symbol or len(symbol) <= 5: # 簡化判定
        return "US"
    return "GLOBAL"
