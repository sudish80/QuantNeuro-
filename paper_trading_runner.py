#!/usr/bin/env python
"""
Paper Trading Runner
=====================

Main execution loop for technical arbitrage strategy on Alpaca paper trading
"""

import os
import time
import logging
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from pathlib import Path
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('paper_trading.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Import our modules
from technical_arbitrage_strategy import TechnicalArbitrageStrategy, SignalType
from paper_trading_monitor import PaperTradingMonitor

# Import Alpaca
try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.enums import Timeframe
    ALPACA_AVAILABLE = True
except ImportError:
    logger.warning("Alpaca library not available - will simulate")
    ALPACA_AVAILABLE = False


class PaperTradingRunner:
    """Execute technical arbitrage strategy on Alpaca paper trading"""
    
    def __init__(self,
                 api_key: str,
                 secret_key: str,
                 symbols: List[str] = None,
                 initial_cash: float = 100000.0,
                 max_position_size: float = 0.05,
                 risk_per_trade: float = 0.02):
        """
        Initialize paper trading runner
        
        Args:
            api_key: Alpaca API key
            secret_key: Alpaca secret key
            symbols: List of symbols to trade (e.g., ['AAPL', 'MSFT', 'GOOGL'])
            initial_cash: Starting cash balance
            max_position_size: Max position as % of portfolio
            risk_per_trade: Risk per trade as % of portfolio
        """
        self.symbols = symbols or ['AAPL', 'MSFT', 'GOOGL', 'AMZN']
        self.initial_cash = initial_cash
        self.max_position_size = max_position_size
        self.risk_per_trade = risk_per_trade
        
        # Initialize Alpaca clients
        if ALPACA_AVAILABLE:
            self.trading_client = TradingClient(api_key, secret_key, paper=True)
            self.data_client = StockHistoricalDataClient(api_key, secret_key)
            logger.info("Connected to Alpaca (PAPER TRADING)")
        else:
            logger.warning("Running in SIMULATION MODE (no real Alpaca connection)")
            self.trading_client = None
            self.data_client = None
        
        # Initialize strategy and monitor
        self.strategy = TechnicalArbitrageStrategy(
            rsi_period=14,
            bb_period=20,
            bb_std=2.0,
            volume_period=20,
            rsi_oversold=30,
            rsi_overbought=70,
            min_lookback=50
        )
        
        self.monitor = PaperTradingMonitor(output_dir="paper_trading_logs")
        
        # Tracking
        self.portfolio_value = initial_cash
        self.open_positions: Dict[str, Dict] = {}  # symbol -> position_info
        self.price_cache: Dict[str, List] = {s: [] for s in self.symbols}
        self.volume_cache: Dict[str, List] = {s: [] for s in self.symbols}
        self.timestamp_cache: Dict[str, List] = {s: [] for s in self.symbols}
        
        logger.info(f"Paper trading runner initialized with {len(self.symbols)} symbols")
    
    def fetch_historical_data(self, symbol: str, bars: int = 100, timeframe: str = "1h") -> bool:
        """
        Fetch historical data for a symbol
        
        Args:
            symbol: Symbol to fetch
            bars: Number of bars
            timeframe: Timeframe ("1h", "1d", etc.)
        
        Returns:
            True if successful
        """
        if not self.data_client:
            logger.warning(f"Data client not available for {symbol}")
            return False
        
        try:
            # Calculate date range
            end_time = datetime.now()
            start_time = end_time - timedelta(days=30)  # 30 days of data
            
            # Fetch bars
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                start=start_time,
                end=end_time,
                timeframe=Timeframe("1H" if timeframe == "1h" else "1D")
            )
            
            bars = self.data_client.get_stock_bars(request)
            
            if symbol not in bars:
                logger.warning(f"No data received for {symbol}")
                return False
            
            bar_list = bars[symbol]
            
            # Extract OHLCV data
            prices = np.array([bar.close for bar in bar_list])
            volumes = np.array([bar.volume for bar in bar_list])
            timestamps = [bar.timestamp.isoformat() for bar in bar_list]
            
            # Cache data
            self.price_cache[symbol] = prices
            self.volume_cache[symbol] = volumes
            self.timestamp_cache[symbol] = timestamps
            
            logger.info(f"Fetched {len(prices)} bars for {symbol}")
            return True
            
        except Exception as e:
            logger.error(f"Error fetching data for {symbol}: {str(e)}")
            return False
    
    def evaluate_symbol(self, symbol: str) -> Optional[Dict]:
        """
        Evaluate symbol for trading signal
        
        Returns:
            Signal info or None
        """
        if symbol not in self.price_cache or len(self.price_cache[symbol]) < 50:
            return None
        
        prices = self.price_cache[symbol]
        volumes = self.volume_cache[symbol]
        timestamps = self.timestamp_cache[symbol]
        
        # Get strategy signal
        signal = self.strategy.evaluate(prices, volumes, timestamps)
        
        if not signal:
            return None
        
        # Log signal
        self.monitor.log_signal(
            symbol=symbol,
            signal_type=signal.signal_type.name,
            rsi=signal.rsi_value,
            price=signal.price,
            confidence=signal.strength,
            reason=signal.reasoning
        )
        
        return {
            'symbol': symbol,
            'signal': signal.signal_type,
            'price': signal.price,
            'confidence': signal.strength,
            'rsi': signal.rsi_value,
            'reasoning': signal.reasoning
        }
    
    def execute_buy_order(self, symbol: str, price: float, reasoning: str) -> Optional[str]:
        """
        Execute buy order
        
        Returns:
            Trade ID or None if failed
        """
        # Calculate position size (risk 2% of portfolio per trade)
        position_size_dollars = self.portfolio_value * self.risk_per_trade
        quantity = int(position_size_dollars / price)
        
        if quantity < 1:
            logger.warning(f"Position size too small for {symbol} (< 1 share)")
            return None
        
        # Check max position size (5% of portfolio)
        max_value = self.portfolio_value * self.max_position_size
        if quantity * price > max_value:
            quantity = int(max_value / price)
            logger.info(f"Capped position size to {quantity} shares")
        
        # Log in monitor
        trade_id = self.monitor.log_trade_entry(
            symbol=symbol,
            entry_price=price,
            quantity=quantity,
            reason=reasoning
        )
        
        # Execute on Alpaca (if connected)
        if self.trading_client:
            try:
                order_request = MarketOrderRequest(
                    symbol=symbol,
                    qty=quantity,
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY
                )
                order = self.trading_client.submit_order(order_request)
                logger.info(f"Buy order submitted for {symbol}: {order.id}")
            except Exception as e:
                logger.error(f"Error submitting buy order: {str(e)}")
        else:
            logger.info(f"[SIMULATION] Would buy {quantity} shares of {symbol} @ ${price:.2f}")
        
        # Track position
        self.open_positions[symbol] = {
            'quantity': quantity,
            'entry_price': price,
            'entry_time': datetime.now(),
            'trade_id': trade_id
        }
        
        return trade_id
    
    def execute_sell_order(self, symbol: str, price: float, reasoning: str) -> Optional[str]:
        """
        Execute sell order for open position
        
        Returns:
            Trade ID or None
        """
        if symbol not in self.open_positions:
            logger.warning(f"No open position for {symbol}")
            return None
        
        position = self.open_positions[symbol]
        quantity = position['quantity']
        trade_id = position['trade_id']
        
        # Log trade exit
        self.monitor.log_trade_exit(
            trade_id=trade_id,
            exit_price=price,
            reason=reasoning
        )
        
        # Execute on Alpaca
        if self.trading_client:
            try:
                order_request = MarketOrderRequest(
                    symbol=symbol,
                    qty=quantity,
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.DAY
                )
                order = self.trading_client.submit_order(order_request)
                logger.info(f"Sell order submitted for {symbol}: {order.id}")
            except Exception as e:
                logger.error(f"Error submitting sell order: {str(e)}")
        else:
            logger.info(f"[SIMULATION] Would sell {quantity} shares of {symbol} @ ${price:.2f}")
        
        # Remove from tracking
        del self.open_positions[symbol]
        
        return trade_id
    
    def run_iteration(self):
        """Run single trading iteration"""
        logger.info("="*70)
        logger.info(f"Trading iteration at {datetime.now():%Y-%m-%d %H:%M:%S}")
        
        for symbol in self.symbols:
            # Fetch latest data
            if not self.fetch_historical_data(symbol):
                continue
            
            # Evaluate for signals
            signal_info = self.evaluate_symbol(symbol)
            
            if not signal_info:
                continue
            
            # Execute trades based on signal
            if signal_info['signal'] == SignalType.BUY and signal_info['confidence'] > 0.4:
                if symbol not in self.open_positions:
                    self.execute_buy_order(
                        symbol,
                        signal_info['price'],
                        signal_info['reasoning']
                    )
            
            elif signal_info['signal'] == SignalType.SELL and signal_info['confidence'] > 0.4:
                if symbol in self.open_positions:
                    self.execute_sell_order(
                        symbol,
                        signal_info['price'],
                        signal_info['reasoning']
                    )
        
        # Print performance snapshot
        self.monitor.print_performance_snapshot()
    
    def run(self, max_iterations: int = None, interval_seconds: int = 3600):
        """
        Run main trading loop
        
        Args:
            max_iterations: Max number of iterations (None = infinite)
            interval_seconds: Seconds between iterations (default 1 hour)
        """
        iteration = 0
        
        logger.info("Starting paper trading session")
        logger.info(f"Symbols: {', '.join(self.symbols)}")
        logger.info(f"Initial cash: ${self.initial_cash:,.2f}")
        logger.info(f"Update interval: {interval_seconds} seconds")
        
        try:
            while True:
                iteration += 1
                
                if max_iterations and iteration > max_iterations:
                    logger.info(f"Reached max iterations ({max_iterations})")
                    break
                
                self.run_iteration()
                
                # Wait for next iteration
                logger.info(f"Next update in {interval_seconds} seconds...")
                time.sleep(interval_seconds)
        
        except KeyboardInterrupt:
            logger.info("Trading stopped by user")
        
        finally:
            self.stop()
    
    def stop(self):
        """Stop trading and save reports"""
        logger.info("Stopping paper trading session")
        
        # Save session report
        report = self.monitor.save_session_report()
        
        # Save config
        config = {
            'symbols': self.symbols,
            'initial_cash': self.initial_cash,
            'max_position_size': self.max_position_size,
            'risk_per_trade': self.risk_per_trade,
            'timestamp': datetime.now().isoformat()
        }
        
        config_path = Path("paper_trading_logs") / f"config_{datetime.now():%Y%m%d_%H%M%S}.json"
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        
        logger.info("Paper trading session saved")


def main():
    """Main entry point"""
    from dotenv import load_dotenv
    
    # Load environment
    load_dotenv()
    
    api_key = os.getenv('ALPACA_API_KEY', 'DEMO')
    secret_key = os.getenv('ALPACA_SECRET_KEY', 'DEMO')
    
    logger.info("Paper Trading Runner Starting")
    logger.info(f"Using API Key: {api_key[:8]}...")
    
    # Create runner
    runner = PaperTradingRunner(
        api_key=api_key,
        secret_key=secret_key,
        symbols=['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA'],
        initial_cash=100000.0,
        max_position_size=0.05,
        risk_per_trade=0.02
    )
    
    # Run with 1-hour interval, max 15 iterations (15 hours for testing)
    runner.run(max_iterations=15, interval_seconds=3600)


if __name__ == "__main__":
    main()
