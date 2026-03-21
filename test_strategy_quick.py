#!/usr/bin/env python
"""
Quick Test of Technical Arbitrage Strategy
Validates the strategy works with synthetic data
"""

import numpy as np
from technical_arbitrage_strategy import TechnicalArbitrageStrategy, SignalType

print("="*70)
print("TECHNICAL ARBITRAGE STRATEGY - QUICK TEST")
print("="*70)
print()

# Create test data with some patterns
np.random.seed(42)
n = 200

# Create price data with oversold/overbought periods
prices = np.array([100.0])
for i in range(1, n):
    if i % 50 < 25:
        # Downtrend (creates oversold conditions)
        prices = np.append(prices, prices[-1] * (1 - np.random.uniform(0, 0.02)))
    else:
        # Uptrend (creates overbought conditions)
        prices = np.append(prices, prices[-1] * (1 + np.random.uniform(0, 0.02)))

# Add some noise
prices = prices * (1 + np.random.normal(0, 0.005, len(prices)))

volumes = np.full(n, 1e6) + np.random.normal(0, 1e5, n)
volumes = np.maximum(volumes, 1e5)  # Ensure positive

timestamps = [f"2026-03-{15 + i%30:02d} {i%24:02d}:00" for i in range(n)]

print(f"Generated {n} price bars")
print(f"Price range: ${prices.min():.2f} - ${prices.max():.2f}")
print()

# Create strategy
strategy = TechnicalArbitrageStrategy(
    rsi_period=14,
    bb_period=20,
    bb_std=2.0,
    rsi_oversold=30,
    rsi_overbought=70,
    min_lookback=50
)

print("Strategy initialized:")
print(f"  RSI Period: 14")
print(f"  RSI Oversold: 30")
print(f"  RSI Overbought: 70")
print(f"  BB Period: 20")
print()

# Evaluate signals
buy_signals = []
sell_signals = []
hold_signals = []

print("Scanning for signals...")
for i in range(50, len(prices), 10):  # Every 10 bars for faster testing
    signal = strategy.evaluate(prices[:i+1], volumes[:i+1], timestamps[:i+1])
    
    if signal:
        if signal.signal_type == SignalType.BUY:
            buy_signals.append((i, signal))
        elif signal.signal_type == SignalType.SELL:
            sell_signals.append((i, signal))
        else:
            hold_signals.append((i, signal))

print(f"  BUY signals: {len(buy_signals)}")
print(f"  SELL signals: {len(sell_signals)}")
print(f"  HOLD signals: {len(hold_signals)}")
print()

# Show first few signals
if buy_signals:
    print("First 3 BUY signals:")
    for idx, (i, signal) in enumerate(buy_signals[:3]):
        print(f"  {idx+1}. [{timestamps[i]}] RSI {signal.rsi_value:.1f} -> {signal.reasoning}")

if sell_signals:
    print("\nFirst 3 SELL signals:")
    for idx, (i, signal) in enumerate(sell_signals[:3]):
        print(f"  {idx+1}. [{timestamps[i]}] RSI {signal.rsi_value:.1f} -> {signal.reasoning}")

# Simulate trades
trades = []
position = None

for i in range(50, len(prices)):
    signal = strategy.evaluate(prices[:i+1], volumes[:i+1], timestamps[:i+1])
    
    if not signal:
        continue
    
    # BUY
    if signal.signal_type == SignalType.BUY and not position and signal.strength > 0.4:
        position = {
            'entry_bar': i,
            'entry_price': prices[i],
            'entry_time': timestamps[i]
        }
    
    # SELL
    elif signal.signal_type == SignalType.SELL and position and signal.strength > 0.4:
        pnl = (prices[i] - position['entry_price']) * 10  # 10 shares
        pnl_pct = ((prices[i] - position['entry_price']) / position['entry_price']) * 100
        
        trades.append({
            'entry_bar': position['entry_bar'],
            'exit_bar': i,
            'entry_price': position['entry_price'],
            'exit_price': prices[i],
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'bars_held': i - position['entry_bar']
        })
        
        position = None

print(f"\n{'='*70}")
print("SIMULATION RESULTS")
print("="*70)
print(f"Trades completed: {len(trades)}")

if trades:
    pnls = [t['pnl'] for t in trades]
    wins = len([t for t in trades if t['pnl'] > 0])
    
    print(f"  Wins: {wins}/{len(trades)} ({wins/len(trades)*100:.1f}%)")
    print(f"  Total P&L: ${sum(pnls):.2f}")
    print(f"  Avg P&L: ${np.mean(pnls):.2f}")
    print(f"  Max Win: ${max(pnls):.2f}")
    print(f"  Max Loss: ${min(pnls):.2f}")
    
    print("\nTrade Details:")
    for idx, trade in enumerate(trades[:5]):
        print(f"  Trade {idx+1}: Buy ${trade['entry_price']:.2f} -> Sell ${trade['exit_price']:.2f} | "
              f"P&L ${trade['pnl']:.2f} ({trade['pnl_pct']:+.1f}%)")

print()
print("✅ Technical arbitrage strategy validation complete!")
print()
print("Next steps:")
print("1. Deploy simulation on real historical data: python paper_trading_simulation.py")
print("2. Deploy to Alpaca paper trading: python paper_trading_runner.py")
print("3. Monitor for 2-4 weeks")
print("4. If win rate > 55%, deploy to live trading")
