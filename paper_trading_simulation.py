#!/usr/bin/env python
"""
Paper Trading Demo - Simulation Mode
=====================================

Runs the technical arbitrage strategy on historical data without
requiring a live Alpaca connection. Great for validation before going live.
"""

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import logging

from technical_arbitrage_strategy import TechnicalArbitrageStrategy, SignalType
from paper_trading_monitor import PaperTradingMonitor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SimulatedPaperTrade:
    """Simulate paper trading using historical data"""
    
    def __init__(self, symbols=['AAPL', 'MSFT', 'GOOGL'], initial_cash=100000):
        self.symbols = symbols
        self.initial_cash = initial_cash
        self.cash = initial_cash
        
        self.strategy = TechnicalArbitrageStrategy(
            rsi_period=14,
            bb_period=20,
            rsi_oversold=30,
            rsi_overbought=70
        )
        
        self.monitor = PaperTradingMonitor()
        self.open_positions = {}
        
    def fetch_symbol_data(self, symbol, period='1mo'):
        """Fetch historical data for symbol"""
        logger.info(f"Fetching {period} of {symbol}...")
        try:
            data = yf.download(symbol, period=period, interval='1h', progress=False)
            if data.empty:
                logger.warning(f"No data for {symbol}")
                return None
            
            return {
                'prices': data['Close'].values,
                'volumes': data['Volume'].values,
                'dates': [str(d) for d in data.index]
            }
        except Exception as e:
            logger.error(f"Error fetching {symbol}: {e}")
            return None
    
    def simulate_trade(self, symbol):
        """Simulate trading for a symbol"""
        data = self.fetch_symbol_data(symbol, period='1mo')
        if not data:
            return
        
        logger.info(f"\nSimulating {symbol} ({len(data['prices'])} bars)...")
        print(f"\n{'='*70}")
        print(f"SIMULATING: {symbol}")
        print(f"{'='*70}")
        
        prices = data['prices']
        volumes = data['volumes']
        dates = data['dates']
        
        trades_executed = 0
        
        # Simulate hour by hour
        for i in range(50, len(prices)):
            # Get signal
            signal = self.strategy.evaluate(
                prices[:i+1],
                volumes[:i+1],
                dates[:i+1]
            )
            
            if not signal or signal.signal_type == SignalType.HOLD:
                continue
            
            current_price = prices[i]
            
            # BUY signal
            if signal.signal_type == SignalType.BUY:
                if symbol not in self.open_positions:
                    # Calculate position size
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
                            'quantity': quantity,
                            'entry_bar': i
                        }
                        
                        self.cash -= quantity * current_price
                        trades_executed += 1
                        
                        logger.info(f"  [{dates[i]}] BUY {quantity} @ ${current_price:.2f}")
            
            # SELL signal
            elif signal.signal_type == SignalType.SELL:
                if symbol in self.open_positions:
                    pos = self.open_positions[symbol]
                    profit = (current_price - pos['entry_price']) * pos['quantity']
                    profit_pct = ((current_price - pos['entry_price']) / pos['entry_price']) * 100
                    
                    self.monitor.log_trade_exit(
                        trade_id=pos['trade_id'],
                        exit_price=current_price,
                        reason=signal.reasoning
                    )
                    
                    self.cash += pos['quantity'] * current_price
                    
                    logger.info(f"  [{dates[i]}] SELL {pos['quantity']} @ ${current_price:.2f} "
                              f"(P&L: ${profit:.2f} / {profit_pct:+.1f}%)")
                    
                    del self.open_positions[symbol]
                    trades_executed += 1
        
        # Close any remaining positions at last price
        if symbol in self.open_positions:
            pos = self.open_positions[symbol]
            last_price = prices[-1]
            profit = (last_price - pos['entry_price']) * pos['quantity']
            profit_pct = ((last_price - pos['entry_price']) / pos['entry_price']) * 100
            
            self.monitor.log_trade_exit(
                trade_id=pos['trade_id'],
                exit_price=last_price,
                reason="End of simulation"
            )
            
            self.cash += pos['quantity'] * last_price
            logger.info(f"  [END] SELL {pos['quantity']} @ ${last_price:.2f} "
                      f"(P&L: ${profit:.2f} / {profit_pct:+.1f}%)")
            del self.open_positions[symbol]
        
        logger.info(f"Executed {trades_executed} trades for {symbol}")
    
    def run_simulation(self):
        """Run complete simulation"""
        print("\n" + "="*70)
        print("PAPER TRADING SIMULATION")
        print(f"Start Cash: ${self.initial_cash:,.2f}")
        print(f"Symbols: {', '.join(self.symbols)}")
        print("="*70)
        
        for symbol in self.symbols:
            try:
                self.simulate_trade(symbol)
            except Exception as e:
                logger.error(f"Error simulating {symbol}: {e}")
        
        # Save report
        self.monitor.save_session_report()
        self.monitor.print_performance_snapshot()


def main():
    """Run simulation"""
    print("\nTechnical Arbitrage Strategy - Paper Trading Simulation")
    print("="*70)
    print("This simulates the technical arbitrage strategy on past data")
    print("to validate the approach before deploying to live Alpaca trading.\n")
    
    simulator = SimulatedPaperTrade(
        symbols=['AAPL', 'MSFT', 'GOOGL', 'AMZN'],
        initial_cash=100000
    )
    
    simulator.run_simulation()
    
    print("\n✅ Simulation complete! Check paper_trading_logs/ for detailed results")
    print("\nNext steps:")
    print("1. Review the simulation results in paper_trading_logs/")
    print("2. If win rate > 55% and Sharpe > 0.5, deploy to Alpaca paper trading")
    print("3. Run: python paper_trading_runner.py")


if __name__ == "__main__":
    main()
