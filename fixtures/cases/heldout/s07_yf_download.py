import yfinance as yf
data = yf.download("AAPL MSFT", start="2024-01-01", end="2024-02-01", progress=False, group_by="ticker")
print(data)
