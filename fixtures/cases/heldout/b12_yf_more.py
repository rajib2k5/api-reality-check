import yfinance as yf
t = yf.Ticker("MSFT")
try:
    print(t.info.get("shortName"), t.fast_info, t.dividends, t.splits, t.actions, t.recommendations, t.calendar, t.news, t.options)
except Exception as e:
    print(e)
print(yf.Tickers("AAPL MSFT").tickers, yf.download(tickers=["AAPL"], period="5d", interval="1h", threads=False, progress=False, auto_adjust=True))
