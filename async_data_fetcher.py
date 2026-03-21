"""
Async data fetching utilities for non-blocking I/O.

Provides concurrent data fetching from multiple sources without blocking:
- Concurrent yfinance downloads
- Batch API requests
- Parallel model inference
- Background data refresh

Useful for:
- Multi-asset portfolio updates
- Real-time streaming during model training
- Concurrent inference on multiple signals
"""

import asyncio
import aiohttp
import pandas as pd
from typing import List, Dict, Optional, Coroutine
from datetime import datetime, timedelta
import yfinance as yf


class AsyncDataFetcher:
    """Concurrent data fetching for multiple tickers/assets."""

    def __init__(self, max_concurrent: int = 5, timeout_seconds: int = 30):
        """
        Initialize async data fetcher.

        Args:
            max_concurrent: Maximum concurrent requests
            timeout_seconds: Request timeout
        """
        self.max_concurrent = max_concurrent
        self.timeout = timeout_seconds
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def fetch_ticker_data(
        self, ticker: str, period: str = "1y", interval: str = "1d"
    ) -> Optional[pd.DataFrame]:
        """
        FIX #6: Fetch historical ticker data with per-task timeout.
        
        Prevents one slow/hanging request from blocking the entire batch.

        Args:
            ticker: Stock/crypto symbol (e.g., "AAPL", "BTC-USD")
            period: Historical period ("1mo", "1y", "5y", etc.)
            interval: Bar interval ("1d", "1h", "15m", etc.)

        Returns:
            DataFrame with OHLCV data or None if timeout
        """
        async with self._semaphore:
            try:
                loop = asyncio.get_event_loop()
                # Add timeout for individual ticker fetch
                data = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: yf.download(ticker, period=period, interval=interval, progress=False),
                    ),
                    timeout=self.timeout  # Per-task timeout
                )
                return data
            except asyncio.TimeoutError:
                print(f"Timeout fetching {ticker} (>{self.timeout}s)")
                return None
            except Exception as e:
                print(f"Error fetching {ticker}: {e}")
                return None

    async def fetch_multiple_tickers(
        self, tickers: List[str], period: str = "1y", use_cache: Optional[Dict] = None
    ) -> Dict[str, pd.DataFrame]:
        """
        FIX #6: Fetch data for multiple tickers with timeout and fallback.

        Much faster than sequential fetching.
        Handles timeouts gracefully by using cache if available.

        Example:
            tickers = ["AAPL", "GOOGL", "MSFT", "TSLA", "AMZN"]
            data = await fetcher.fetch_multiple_tickers(tickers)
            # Returns: {"AAPL": df, "GOOGL": df, ...}
            # If timeout: returns cached data instead of blocking
        """
        use_cache = use_cache or {}
        results = {}
        
        # Create tasks with individual timeouts
        tasks = {
            ticker: asyncio.create_task(self.fetch_ticker_data(ticker, period=period))
            for ticker in tickers
        }
        
        # Wait for all tasks with overall timeout
        overall_timeout = self.timeout * len(tickers) / self.max_concurrent
        try:
            completed, pending = await asyncio.wait(
                tasks.values(),
                timeout=overall_timeout,
                return_when=asyncio.ALL_COMPLETED
            )
            
            # Cancel any still-pending tasks
            for task in pending:
                task.cancel()
                
        except Exception as e:
            print(f"Batch fetch error: {e}")
        
        # Collect results, using cache for failed/timed-out requests
        for ticker, task in tasks.items():
            try:
                data = task.result() if task.done() else None
                if data is not None and len(data) > 0:
                    results[ticker] = data
                elif ticker in use_cache:
                    print(f"Using cached data for {ticker}")
                    results[ticker] = use_cache[ticker]
                else:
                    results[ticker] = pd.DataFrame()
            except (asyncio.CancelledError, asyncio.TimeoutError):
                if ticker in use_cache:
                    print(f"Request for {ticker} timed out, using cache")
                    results[ticker] = use_cache[ticker]
                else:
                    print(f"Request for {ticker} timed out, no cache available")
                    results[ticker] = pd.DataFrame()
            except Exception as e:
                print(f"Error collecting {ticker}: {e}")
                results[ticker] = pd.DataFrame()
        
        return results

    async def fetch_intraday_batch(
        self, tickers: List[str], interval: str = "5m"
    ) -> Dict[str, pd.DataFrame]:
        """Fetch intraday data for multiple tickers concurrently."""
        return await self.fetch_multiple_tickers(tickers, period="1d")


class AsyncAPIClient:
    """Non-blocking HTTP client for API requests."""

    def __init__(self, max_concurrent: int = 10, timeout_seconds: int = 30):
        """
        Initialize async HTTP client.

        Args:
            max_concurrent: Max concurrent HTTP connections
            timeout_seconds: Request timeout
        """
        self.max_concurrent = max_concurrent
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def fetch_json(self, url: str, headers: Optional[Dict] = None) -> Dict:
        """
        Fetch JSON from URL asynchronously.

        Args:
            url: API endpoint URL
            headers: Optional HTTP headers

        Returns:
            Parsed JSON response
        """
        async with self._semaphore:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        raise Exception(f"API error: {response.status}")

    async def fetch_multiple_urls(self, urls: List[str], return_on_first_timeout: bool = False) -> List:
        """
        FIX #6: Fetch multiple URLs concurrently with timeout handling.
        
        Args:
            urls: List of API URLs
            return_on_first_timeout: If True, return immediately on first timeout
                                       If False, continue with other requests
        
        Returns:
            List of responses (exceptions included if return_exceptions=True)
        """
        tasks = [
            asyncio.create_task(self.fetch_json(url))
            for url in urls
        ]
        
        try:
            # Use asyncio.wait for better control over timeouts
            done, pending = await asyncio.wait(
                tasks,
                timeout=self.timeout.total,
                return_when=asyncio.ALL_COMPLETED if not return_on_first_timeout else asyncio.FIRST_EXCEPTION
            )
            
            # Cancel remaining pending tasks
            for task in pending:
                task.cancel()
            
            # Collect results
            results = []
            for task in tasks:
                try:
                    if task.done():
                        results.append(task.result())
                    else:
                        results.append(TimeoutError(f"Request timed out"))
                except Exception as e:
                    results.append(e)
            
            return results
        
        except Exception as e:
            print(f"Batch URL fetch error: {e}")
            # Return empty results for all on critical failure
            return [None] * len(urls)

    async def post_json(self, url: str, data: Dict, headers: Optional[Dict] = None) -> Dict:
        """
        POST JSON to URL asynchronously.

        Args:
            url: API endpoint URL
            data: JSON payload
            headers: Optional HTTP headers

        Returns:
            Parsed JSON response
        """
        async with self._semaphore:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(url, json=data, headers=headers) as response:
                    if response.status in [200, 201]:
                        return await response.json()
                    else:
                        raise Exception(f"API error: {response.status}")


class BatchInferencePipeline:
    """
    Concurrent model inference on multiple inputs.

    Example: Generate predictions for 100+ tickers without blocking.
    """

    def __init__(self, batch_size: int = 32, max_concurrent_batches: int = 4):
        """
        Initialize batch inference.

        Args:
            batch_size: Samples per batch
            max_concurrent_batches: Concurrent batch processes
        """
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent_batches
        self._semaphore = asyncio.Semaphore(max_concurrent_batches)

    async def infer_batch(self, model, inputs_batch, device) -> List:
        """
        Run inference on a batch asynchronously.

        Args:
            model: PyTorch model
            inputs_batch: Batch of input tensors
            device: Torch device (cpu/cuda)

        Returns:
            List of predictions
        """
        async with self._semaphore:
            loop = asyncio.get_event_loop()
            # Run inference in thread pool to avoid blocking
            predictions = await loop.run_in_executor(
                None,
                lambda: self._inference_impl(model, inputs_batch, device),
            )
            return predictions

    @staticmethod
    def _inference_impl(model, inputs_batch, device):
        """Synchronous inference implementation (runs in thread pool)."""
        import torch

        with torch.no_grad():
            inputs = torch.tensor(inputs_batch, dtype=torch.float32).to(device)
            outputs = model(inputs)
            return outputs.cpu().numpy()

    async def infer_multiple_batches(self, model, all_inputs, device, batch_size: int = None):
        """
        Infer on multiple batches concurrently.

        Args:
            model: PyTorch model
            all_inputs: All input samples
            device: Torch device
            batch_size: Optional override batch size

        Returns:
            List of all predictions
        """
        batch_size = batch_size or self.batch_size

        # Create batches
        batches = [
            all_inputs[i : i + batch_size]
            for i in range(0, len(all_inputs), batch_size)
        ]

        # Infer all batches concurrently
        tasks = [self.infer_batch(model, batch, device) for batch in batches]
        batch_results = await asyncio.gather(*tasks)

        # Flatten results
        all_predictions = []
        for batch_preds in batch_results:
            all_predictions.extend(batch_preds)

        return all_predictions


# ============================================================================
# Helper Functions
# ============================================================================


async def fetch_portfolio_data(tickers: List[str], period: str = "1y") -> Dict[str, pd.DataFrame]:
    """
    Fetch historical data for entire portfolio concurrently.

    Much faster than sequential fetching for large portfolios.

    Example:
        portfolio = ["AAPL", "GOOGL", "MSFT", "TSLA", "AMZN", "NVDA", "META"]
        data = await fetch_portfolio_data(portfolio)
        # ~5 seconds vs 15-20 seconds sequential
    """
    fetcher = AsyncDataFetcher(max_concurrent=10)
    return await fetcher.fetch_multiple_tickers(tickers, period=period)


async def fetch_realtime_prices(tickers: List[str]) -> Dict[str, float]:
    """
    Fetch latest prices for multiple tickers asynchronously.

    Example:
        prices = await fetch_realtime_prices(["BTC-USD", "ETH-USD", "SOL-USD"])
    """
    fetcher = AsyncDataFetcher()
    data_dict = await fetcher.fetch_multiple_tickers(tickers, period="1d")

    prices = {}
    for ticker, data in data_dict.items():
        if not data.empty:
            prices[ticker] = float(data.iloc[-1]["Close"])

    return prices


async def concurrent_predictions(
    model, tickers: List[str], device
) -> Dict[str, float]:
    """
    Generate predictions for multiple tickers concurrently.

    Combines async data fetching + batch inference.

    Example:
        predictions = await concurrent_predictions(model, ["AAPL", "GOOGL", "MSFT"])
        # {"AAPL": 155.23, "GOOGL": 142.05, "MSFT": 378.91}
    """
    from preprocessing import prepare_dataset

    # Fetch data concurrently
    data_dict = await fetch_portfolio_data(tickers)

    # Prepare inputs (can be parallelize further if needed)
    all_inputs = []
    ticker_order = []
    for ticker, data in data_dict.items():
        if not data.empty:
            all_inputs.append(data)
            ticker_order.append(ticker)

    if not all_inputs:
        return {}

    # Infer concurrently
    pipeline = BatchInferencePipeline(batch_size=32, max_concurrent_batches=4)

    # Stack data into batch
    import numpy as np

    # Simplified: convert to features (full version would use prepare_dataset logic)
    batch_array = np.array([d.values[-20:] for d in all_inputs])

    predictions = await pipeline.infer_multiple_batches(model, batch_array, device)

    return {ticker: float(pred) for ticker, pred in zip(ticker_order, predictions)}


# ============================================================================
# Background Task Manager
# ============================================================================


class BackgroundDataRefresher:
    """
    Periodically refresh data in background without blocking main loop.

    Useful for keeping cache fresh during paper trading or simulation.
    """

    def __init__(self, tickers: List[str], refresh_interval_seconds: int = 60):
        """
        Initialize background refresher.

        Args:
            tickers: Tickers to refresh
            refresh_interval_seconds: Refresh frequency
        """
        self.tickers = tickers
        self.interval = refresh_interval_seconds
        self.cache = {}
        self.last_update = None
        self._running = False

    async def start(self):
        """Start background refresh loop."""
        self._running = True
        while self._running:
            try:
                self.cache = await fetch_portfolio_data(self.tickers, period="5d")
                self.last_update = datetime.utcnow()
                print(f"✓ Data cache refreshed: {len(self.cache)} tickers")
            except Exception as e:
                print(f"✗ Cache refresh error: {e}")

            # Sleep without blocking
            await asyncio.sleep(self.interval)

    async def stop(self):
        """Stop background refresh loop."""
        self._running = False

    def get_cached_data(self, ticker: str) -> Optional[pd.DataFrame]:
        """Get cached data for ticker."""
        return self.cache.get(ticker)


# ============================================================================
# Example Usage
# ============================================================================

if __name__ == "__main__":
    import time

    async def main():
        """Example: Fetch multiple tickers concurrently."""
        print("Async Data Fetcher Examples")
        print("=" * 60)

        # Example 1: Fetch single ticker
        print("\n1. Single Ticker (async):")
        fetcher = AsyncDataFetcher()
        data = await fetcher.fetch_ticker_data("AAPL", period="1mo")
        print(f"   Fetched {len(data)} rows for AAPL")

        # Example 2: Fetch multiple tickers concurrently
        print("\n2. Multiple Tickers (concurrent):")
        start = time.time()
        tickers = ["AAPL", "GOOGL", "MSFT", "TSLA", "AMZN"]
        data_dict = await fetcher.fetch_multiple_tickers(tickers, period="1mo")
        elapsed = time.time() - start
        print(f"   Fetched {len(data_dict)} tickers in {elapsed:.2f}s")
        for ticker, data in data_dict.items():
            print(f"     {ticker}: {len(data)} rows")

        # Example 3: Real-time prices
        print("\n3. Real-time Prices (concurrent):")
        prices = await fetch_realtime_prices(["AAPL", "GOOGL", "MSFT"])
        for ticker, price in prices.items():
            print(f"   {ticker}: ${price:.2f}")

        print("\n✓ All async operations completed!")

    # Run examples
    asyncio.run(main())
