"""Data collection and cleaning algorithms for stock and crypto prediction."""

import requests
import yfinance as yf
import pandas as pd


# Common tickers for stocks and crypto
STOCK_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA"]
CRYPTO_TICKERS = ["BTC-USD", "ETH-USD", "SOL-USD", "ADA-USD", "XRP-USD"]


def _postprocess_ohlcv(data: pd.DataFrame) -> pd.DataFrame:
    """Ensure standard OHLCV shape and cleaned, sorted timestamp index."""
    if data.empty:
        raise ValueError("Received empty market data")
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    required = ["Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in required if c not in data.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    cleaned = data.copy()
    if not isinstance(cleaned.index, pd.DatetimeIndex):
        cleaned.index = pd.to_datetime(cleaned.index, errors="coerce", utc=True)
    else:
        cleaned.index = cleaned.index.tz_localize("UTC") if cleaned.index.tz is None else cleaned.index.tz_convert("UTC")

    cleaned = cleaned[~cleaned.index.isna()]
    cleaned = cleaned[~cleaned.index.duplicated(keep="last")]
    cleaned = cleaned.dropna(subset=required)
    cleaned = cleaned.sort_index()
    return cleaned


def fetch_data_yahoo(ticker: str, period: str = "5y", interval: str = "1d") -> pd.DataFrame:
    """
    Fetch historical price data for a given ticker.

    Args:
        ticker: Yahoo Finance ticker symbol (e.g., 'AAPL', 'BTC-USD').
        period: How far back to fetch ('1y', '2y', '5y', '10y', 'max').
        interval: Data granularity ('1d', '1wk', '1mo').

    Returns:
        DataFrame with columns: Open, High, Low, Close, Volume, plus
        computed features: Returns, MA_20, MA_50, Volatility.
    """
    data = yf.download(ticker, period=period, interval=interval, progress=False)
    return _postprocess_ohlcv(data)


def fetch_data_binance(symbol: str = "BTCUSDT", interval: str = "1d", limit: int = 1000) -> pd.DataFrame:
    """REST API polling from Binance public klines endpoint."""
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()
    rows = response.json()
    cols = [
        "OpenTime",
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
        "CloseTime",
        "QuoteAssetVolume",
        "NumTrades",
        "TakerBuyBase",
        "TakerBuyQuote",
        "Ignore",
    ]
    df = pd.DataFrame(rows, columns=cols)
    for c in ["Open", "High", "Low", "Close", "Volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["Date"] = pd.to_datetime(df["OpenTime"], unit="ms")
    df = df.set_index("Date")[["Open", "High", "Low", "Close", "Volume"]]
    return _postprocess_ohlcv(df)


def fetch_data_alpha_vantage(symbol: str, api_key: str) -> pd.DataFrame:
    """REST polling from Alpha Vantage daily adjusted endpoint."""
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "TIME_SERIES_DAILY_ADJUSTED",
        "symbol": symbol,
        "outputsize": "full",
        "apikey": api_key,
    }
    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()
    payload = response.json()
    key = "Time Series (Daily)"
    if key not in payload:
        raise ValueError(f"Alpha Vantage response missing '{key}'")

    ts = pd.DataFrame.from_dict(payload[key], orient="index")
    ts.index = pd.to_datetime(ts.index)
    ts = ts.rename(
        columns={
            "1. open": "Open",
            "2. high": "High",
            "3. low": "Low",
            "4. close": "Close",
            "6. volume": "Volume",
        }
    )
    ts = ts[["Open", "High", "Low", "Close", "Volume"]].apply(pd.to_numeric, errors="coerce")
    return _postprocess_ohlcv(ts)


def fetch_data(
    ticker: str,
    period: str = "5y",
    interval: str = "1d",
    source: str = "yahoo",
    alpha_vantage_key: str | None = None,
) -> pd.DataFrame:
    """Source selector: yahoo, binance, alphavantage."""
    source = source.lower()
    if source == "yahoo":
        return fetch_data_yahoo(ticker=ticker, period=period, interval=interval)
    if source == "binance":
        return fetch_data_binance(symbol=ticker, interval=interval)
    if source == "alphavantage":
        if not alpha_vantage_key:
            raise ValueError("alpha_vantage_key is required for alphavantage source")
        return fetch_data_alpha_vantage(symbol=ticker, api_key=alpha_vantage_key)
    raise ValueError("source must be one of: yahoo, binance, alphavantage")


def fetch_multiple(
    tickers: list[str],
    period: str = "5y",
    source: str = "yahoo",
    alpha_vantage_key: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Fetch data for multiple tickers and return as a dict."""
    results = {}
    for ticker in tickers:
        try:
            results[ticker] = fetch_data(
                ticker=ticker,
                period=period,
                source=source,
                alpha_vantage_key=alpha_vantage_key,
            )
            print(f"  Fetched {len(results[ticker])} rows for {ticker}")
        except Exception as e:
            print(f"  Failed to fetch {ticker}: {e}")
    return results
