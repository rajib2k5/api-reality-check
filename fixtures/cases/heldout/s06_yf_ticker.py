import yfinance as yf
t = yf.Ticker("AAPL")
h = t.history(period="1mo", interval="1d", auto_adjust=True)
print(h)
