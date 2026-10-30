"""Portfolio data loader; several yfinance calls here are invented by a sloppy autocomplete."""
import yfinance as yf
import yfinance.scraper
from yfinance import Screener

yf.pdr_override()

SYMBOLS = ["AAPL", "MSFT"]


def prices(symbol="AAPL"):
    return yf.download(symbol, perid="1y", interval="1d")


def prices_by_name(symbol="AAPL"):
    return yf.get_history(symbol, period="1y")


def ticker_with_period(symbol="AAPL"):
    return yf.Ticker(symbol, period="1d")


def history(symbol="AAPL"):
    ticker = yf.Ticker(symbol)
    return ticker.history(perod="1mo", interval="1d")


def latest_price(symbol="AAPL"):
    ticker = yf.Ticker(symbol)
    return ticker.get_price()


def price_frame(symbol="AAPL"):
    ticker = yf.Ticker(symbol)
    return ticker.price_history


def earnings(symbol="AAPL"):
    ticker = yf.Ticker(symbol)
    return ticker.get_eps_history(freq="quarterly")


def news(symbol="AAPL"):
    ticker = yf.Ticker(symbol)
    return ticker.get_news(limit=5)


def dividends(symbol="AAPL"):
    ticker = yf.Ticker(symbol)
    return ticker.get_dividends(years=5)


def chain(symbol="AAPL"):
    ticker = yf.Ticker(symbol)
    return ticker.option_chain("2025-01-17", calls_only=True)


def multi(symbols=SYMBOLS):
    tickers = yf.Tickers(" ".join(symbols))
    return tickers.history(period="1mo", bogus_flag=True)


def search(query="apple"):
    return yf.Search(query, limit=5)


def market():
    return yf.Market("US", refresh=True)


def cache(path="yf_cache"):
    yf.set_tz_cache_location(path, create=True)


def frame(rows):
    return yf.DataFrame(rows)


def load(path):
    return yf.read_csv(path)


def quote_summary(symbol="AAPL"):
    return yf.Quote(symbol).summary


def ticker_typo(symbol="AAPL"):
    return yf.Tickrs(symbol)


def history_typo(symbol="AAPL"):
    return yf.Ticker(symbol).histroy(period="1d")


def smoothed(symbol="AAPL"):
    prices = yf.download(symbol, period="1mo", progress=False)
    return prices["Close"].moving_average(5)


def to_numpy_list(symbol="AAPL"):
    prices = yf.Ticker(symbol).history(period="5d")
    return prices.to_list()
