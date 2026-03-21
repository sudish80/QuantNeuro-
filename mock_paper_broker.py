#!/usr/bin/env python
"""
Mock Paper Broker - Complete Paper Trading Simulator
No API keys needed. Trades synthetic market data with realistic OHLCV.
"""

import numpy as np
import pandas as pd
import json
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

from technical_arbitrage_strategy import TechnicalArbitrageStrategy, SignalType
from paper_trading_monitor import PaperTradingMonitor


@dataclass
class MockMarketData:
    """Realistic synthetic market data"""
    symbol: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class MockMarketGenerator:
    """Generate realistic market data with patterns"""
    
    def __init__(self, seed: int = 42):
        np.random.seed(seed)
        self.symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA']
        self.current_prices = {s: 100.0 * (1 + np.random.uniform(-0.2, 0.2)) for s in self.symbols}
        self.volatility = {s: np.random.uniform(0.01, 0.03) for s in self.symbols}
        self.trend = {s: np.random.uniform(-0.0005, 0.0005) for s in self.symbols}
    
    def generate_bar(self, symbol: str, timestamp: str) -> MockMarketData:
        """Generate single OHLCV bar with patterns"""
        
        # Get current price
        price = self.current_prices[symbol]
        
        # Add trend (momentum)
        price = price * (1 + self.trend[symbol])
        
        # Random walk with volatility
        intraday_return = np.random.normal(0, self.volatility[symbol])
        
        # Generate OHLCV
        open_price = price
        close_price = price * (1 + intraday_return)
        high_price = max(open_price, close_price) * (1 + abs(np.random.normal(0, self.volatility[symbol] * 0.5)))
        low_price = min(open_price, close_price) * (1 - abs(np.random.normal(0, self.volatility[symbol] * 0.5)))
        volume = np.random.lognormal(mean=14, sigma=0.5)  # ~1.2M shares typical
        
        # Persist price
        self.current_prices[symbol] = close_price
        
        # Occasionally shift trend
        if np.random.random() < 0.1:
            self.trend[symbol] = np.random.uniform(-0.0005, 0.0005)
        
        return MockMarketData(
            symbol=symbol,
            timestamp=timestamp,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=volume
        )


class MockPaperBroker:
    """Mock broker - executes trades on synthetic data"""
    
    def __init__(self, initial_cash: float = 100000, num_bars: int = 500):
        """
        Initialize mock broker
        
        Args:
            initial_cash: Starting cash
            num_bars: Number of bars to simulate
        """
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.num_bars = num_bars
        
        self.strategy = TechnicalArbitrageStrategy()
        self.monitor = PaperTradingMonitor()
        self.market_gen = MockMarketGenerator(seed=42)
        
        # Tracking
        self.open_positions: Dict[str, Dict] = {}
        self.symbol_data: Dict[str, List] = {s: {'prices': [], 'volumes': [], 'timestamps': []} 
                                             for s in self.market_gen.symbols}
        
        print("="*70)
        print("MOCK PAPER BROKER - FULLY SIMULATED TRADING")
        print("="*70)
        print(f"Initial Cash: ${self.initial_cash:,.2f}")
        print(f"Symbols: {', '.join(self.market_gen.symbols)}")
        print(f"Simulating {num_bars} bars of market data")
        print()
    
    def run_simulation(self):
        """Run complete simulation"""
        
        # Generate timestamps
        base_time = datetime(2026, 3, 1, 9, 30)  # Market open
        
        for bar_num in range(self.num_bars):
            current_time = base_time + timedelta(hours=bar_num)
            timestamp = current_time.strftime('%Y-%m-%d %H:%M')
            
            # Generate market data for all symbols
            for symbol in self.market_gen.symbols:
                bar = self.market_gen.generate_bar(symbol, timestamp)
                
                # Store data
                self.symbol_data[symbol]['prices'].append(bar.close)
                self.symbol_data[symbol]['volumes'].append(bar.volume)
                self.symbol_data[symbol]['timestamps'].append(timestamp)
                
                # Log price
                self.monitor.log_price_data(symbol, bar.close, bar.volume)
            
            # Every 10 bars, check for signals
            if bar_num > 0 and bar_num % 10 == 0:
                self._check_signals(current_time)
            
            # Print progress every 50 bars
            if bar_num % 50 == 0 and bar_num > 0:
                summary = self.monitor.get_performance_summary()
                print(f"Bar {bar_num:3d} ({timestamp}): {summary['closed_trades']} closed trades, "
                      f"{summary['win_rate']:.1%} W/L, P&L ${summary['total_pnl']:.2f}")
        
        # Close any remaining positions at last price
        self._close_all_positions()
        
        # Print final results
        print()
        self.monitor.save_session_report()
    
    def _check_signals(self, current_time: datetime):
        """Check for trading signals"""
        
        for symbol in self.market_gen.symbols:
            prices = np.array(self.symbol_data[symbol]['prices'])
            volumes = np.array(self.symbol_data[symbol]['volumes'])
            timestamps = self.symbol_data[symbol]['timestamps']
            
            # Get signal
            signal = self.strategy.evaluate(prices, volumes, timestamps)
            
            if not signal:
                continue
            
            # Log signal
            self.monitor.log_signal(
                symbol=symbol,
                signal_type=signal.signal_type.name,
                rsi=signal.rsi_value,
                price=signal.price,
                confidence=signal.strength,
                reason=signal.reasoning
            )
            
            current_price = prices[-1]
            
            # BUY
            if signal.signal_type == SignalType.BUY and signal.strength > 0.4:
                if symbol not in self.open_positions:
                    position_value = self.cash * 0.02  # 2% per trade
                    quantity = int(position_value / current_price)
                    
                    if quantity > 0 and self.cash >= quantity * current_price:
                        trade_id = self.monitor.log_trade_entry(
                            symbol=symbol,
                            entry_price=current_price,
                            quantity=quantity,
                            reason=signal.reasoning
                        )
                        
                        self.open_positions[symbol] = {
                            'trade_id': trade_id,
                            'entry_price': current_price,
                            'quantity': quantity
                        }
                        
                        self.cash -= quantity * current_price
            
            # SELL
            elif signal.signal_type == SignalType.SELL and signal.strength > 0.4:
                if symbol in self.open_positions:
                    pos = self.open_positions[symbol]
                    
                    self.monitor.log_trade_exit(
                        trade_id=pos['trade_id'],
                        exit_price=current_price,
                        reason=signal.reasoning
                    )
                    
                    self.cash += pos['quantity'] * current_price
                    del self.open_positions[symbol]
    
    def _close_all_positions(self):
        """Close all remaining positions"""
        
        for symbol in list(self.open_positions.keys()):
            prices = np.array(self.symbol_data[symbol]['prices'])
            last_price = prices[-1]
            
            pos = self.open_positions[symbol]
            self.monitor.log_trade_exit(
                trade_id=pos['trade_id'],
                exit_price=last_price,
                reason="End of simulation"
            )
            
            self.cash += pos['quantity'] * last_price
            del self.open_positions[symbol]


def main():
    """Run mock paper broker simulation"""
    
    print("\n" + "="*70)
    print("NO API KEYS NEEDED - FULLY SIMULATED PAPER TRADING")
    print("="*70 + "\n")
    
    # Run 500 bars (~2 weeks of trading data)
    broker = MockPaperBroker(
        initial_cash=100000,
        num_bars=500
    )
    
    broker.run_simulation()
    
    print("\n✅ Simulation complete!")
    print("\nResults saved to: paper_trading_logs/")
    print("\nNext steps:")
    print("1. Review performance in paper_trading_logs/session_*.json")
    print("2. If win rate > 55%, deploy to real Alpaca paper trading")
    print("3. Or run again with different parameters")


if __name__ == "__main__":
    main()
