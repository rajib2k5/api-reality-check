"""Market-data helpers built on yfinance. Every function needs the network when called."""
import pandas as pd
import yfinance as yf

SYMBOLS = ["AAPL", "MSFT", "NVDA"]


def daily_history(symbol="AAPL"):
    ticker = yf.Ticker(symbol)
    prices = ticker.history(period="6mo", interval="1d", auto_adjust=True, actions=False)
    return prices["Close"].rolling(window=20).mean()


def ranged_history(symbol="AAPL"):
    return yf.Ticker(symbol).history(start="2024-01-01", end="2024-03-01", interval="1h", prepost=False)


def bulk_download():
    return yf.download(
        SYMBOLS,
        start="2023-01-01",
        end="2024-01-01",
        interval="1d",
        group_by="ticker",
        auto_adjust=True,
        progress=False,
        threads=True,
        timeout=20,
    )


def single_download(symbol="AAPL"):
    return yf.download(symbol, period="1y", interval="1wk", multi_level_index=False)


def company_profile(symbol="AAPL"):
    info = yf.Ticker(symbol).info
    return {"name": info.get("longName"), "sector": info.get("sector"), "pe": info.get("trailingPE")}


def info_dict(symbol="AAPL"):
    return yf.Ticker(symbol).get_info()


def last_price(symbol="AAPL"):
    fast = yf.Ticker(symbol).fast_info
    return fast["lastPrice"], fast["marketCap"]


def dividend_history(symbol="AAPL"):
    ticker = yf.Ticker(symbol)
    return ticker.get_dividends(period="5y").resample("YE").sum()


def dividends_attr(symbol="AAPL"):
    return yf.Ticker(symbol).dividends


def split_history(symbol="AAPL"):
    return yf.Ticker(symbol).splits


def corporate_actions(symbol="AAPL"):
    return yf.Ticker(symbol).actions


def income_statement(symbol="AAPL"):
    return yf.Ticker(symbol).get_income_stmt(as_dict=False, pretty=True, freq="quarterly")


def balance_sheet(symbol="AAPL"):
    return yf.Ticker(symbol).get_balance_sheet(freq="yearly")


def cash_flow(symbol="AAPL"):
    return yf.Ticker(symbol).cashflow


def statements_attr(symbol="AAPL"):
    ticker = yf.Ticker(symbol)
    return ticker.financials, ticker.quarterly_financials, ticker.balance_sheet, ticker.income_stmt


def option_expirations(symbol="AAPL"):
    ticker = yf.Ticker(symbol)
    expirations = ticker.options
    chain = ticker.option_chain(expirations[0])
    return chain.calls, chain.puts


def latest_news(symbol="AAPL"):
    return yf.Ticker(symbol).get_news(count=5, tab="news")


def holders(symbol="AAPL"):
    ticker = yf.Ticker(symbol)
    return ticker.major_holders, ticker.institutional_holders


def analyst_view(symbol="AAPL"):
    ticker = yf.Ticker(symbol)
    return ticker.recommendations, ticker.analyst_price_targets, ticker.upgrades_downgrades


def earnings_calendar(symbol="AAPL"):
    ticker = yf.Ticker(symbol)
    return ticker.get_earnings_dates(limit=8), ticker.calendar


def shares_outstanding(symbol="AAPL"):
    return yf.Ticker(symbol).get_shares_full(start="2023-01-01", end=None)


def history_meta(symbol="AAPL"):
    return yf.Ticker(symbol).history_metadata


def multi_ticker(symbols=SYMBOLS):
    tickers = yf.Tickers(" ".join(symbols))
    first = tickers.tickers[symbols[0]]
    return first.info, tickers.history(period="5d", group_by="ticker")


def symbol_search(query="apple"):
    search = yf.Search(query, max_results=5, news_count=3)
    return search.quotes, search.news


def symbol_lookup(query="apple"):
    return yf.Lookup(query).get_stock(count=10)


def market_summary():
    return yf.Market("US", timeout=15).summary


def sector_overview(key="technology"):
    sector = yf.Sector(key)
    return sector.overview, sector.top_companies


def industry_overview(key="software-infrastructure"):
    return yf.Industry(key, region="US").top_companies


def screen_large_caps():
    query = yf.EquityQuery(
        "and",
        [yf.EquityQuery("eq", ["region", "us"]), yf.EquityQuery("gt", ["intradaymarketcap", 1_000_000_000])],
    )
    return yf.screen(query, size=25, sortField="intradaymarketcap", sortAsc=False)


def configure_cache(path="yf_cache"):
    yf.set_tz_cache_location(path)
    return pd.Timestamp("2024-01-02", tz="UTC")
