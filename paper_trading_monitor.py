#!/usr/bin/env python
"""
Paper Trading Monitor & Logger

Tracks all trades, performance metrics, and logs data for analysis
"""

import json
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    """Single trade record"""
    trade_id: str
    symbol: str
    entry_time: str
    entry_price: float
    entry_reason: str
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    quantity: int = 0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    win: bool = False
    status: str = "open"  # open, closed, cancelled
    
    def close(self, exit_price: float, exit_reason: str):
        """Close the trade"""
        self.exit_price = exit_price
        self.exit_reason = exit_reason
        self.exit_time = datetime.now().isoformat()
        self.pnl = (exit_price - self.entry_price) * self.quantity
        self.pnl_pct = ((exit_price - self.entry_price) / self.entry_price) * 100 if self.entry_price else 0
        self.win = self.pnl > 0
        self.status = "closed"


class PaperTradingMonitor:
    """Monitor and log paper trading performance"""
    
    def __init__(self, output_dir: str = "paper_trading_logs"):
        """
        Initialize monitor
        
        Args:
            output_dir: Directory to save logs
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        self.trades: Dict[str, TradeRecord] = {}
        self.trade_counter = 0
        self.session_start = datetime.now()
        self.price_history: List[Dict] = []
        self.signal_history: List[Dict] = []
        self.performance_history: List[Dict] = []
        
        logger.info(f"Paper trading monitor initialized. Output: {self.output_dir}")
    
    def log_trade_entry(self, 
                        symbol: str,
                        entry_price: float,
                        quantity: int,
                        reason: str) -> str:
        """
        Log trade entry
        
        Returns:
            Trade ID
        """
        self.trade_counter += 1
        trade_id = f"TRADE_{self.trade_counter:05d}"
        
        trade = TradeRecord(
            trade_id=trade_id,
            symbol=symbol,
            entry_time=datetime.now().isoformat(),
            entry_price=entry_price,
            quantity=quantity,
            entry_reason=reason,
            status="open"
        )
        
        self.trades[trade_id] = trade
        logger.info(f"{trade_id}: BUY {quantity} {symbol} @ ${entry_price:.2f} - {reason}")
        
        return trade_id
    
    def log_trade_exit(self,
                       trade_id: str,
                       exit_price: float,
                       reason: str):
        """Log trade exit"""
        if trade_id not in self.trades:
            logger.warning(f"Trade {trade_id} not found")
            return
        
        trade = self.trades[trade_id]
        trade.close(exit_price, reason)
        
        logger.info(f"{trade_id}: SELL {trade.quantity} {trade.symbol} @ ${exit_price:.2f}")
        logger.info(f"  P&L: ${trade.pnl:.2f} ({trade.pnl_pct:+.2f}%)")
    
    def log_signal(self,
                   symbol: str,
                   signal_type: str,
                   rsi: float,
                   price: float,
                   confidence: float,
                   reason: str):
        """Log trading signal"""
        record = {
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'signal': signal_type,
            'rsi': rsi,
            'price': price,
            'confidence': confidence,
            'reason': reason
        }
        self.signal_history.append(record)
        logger.info(f"SIGNAL {symbol}: {signal_type} @ ${price:.2f} (RSI {rsi:.1f}, confidence {confidence:.1%})")
    
    def log_price_data(self,
                       symbol: str,
                       price: float,
                       volume: float,
                       bid: Optional[float] = None,
                       ask: Optional[float] = None):
        """Log price data"""
        record = {
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'price': price,
            'volume': volume,
            'bid': bid,
            'ask': ask
        }
        self.price_history.append(record)
    
    def get_performance_summary(self) -> Dict:
        """Get performance summary"""
        closed_trades = [t for t in self.trades.values() if t.status == "closed"]
        open_trades = [t for t in self.trades.values() if t.status == "open"]
        
        if not closed_trades:
            return {
                'total_trades': len(self.trades),
                'closed_trades': 0,
                'open_trades': len(open_trades),
                'wins': 0,
                'losses': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'avg_pnl': 0.0,
                'avg_pnl_pct': 0.0,
                'sharpe_ratio': 0.0,
                'max_drawdown': 0.0
            }
        
        wins = len([t for t in closed_trades if t.win])
        losses = len([t for t in closed_trades if not t.win])
        total_pnl = sum(t.pnl for t in closed_trades)
        pnl_values = [t.pnl_pct for t in closed_trades]
        
        # Calculate Sharpe ratio (simplified)
        if len(pnl_values) > 1:
            returns_std = pd.Series(pnl_values).std()
            sharpe = (pd.Series(pnl_values).mean() / returns_std * np.sqrt(252)) if returns_std > 0 else 0
        else:
            sharpe = 0.0
        
        # Calculate max drawdown
        cumulative_pnl = np.cumsum([t.pnl for t in closed_trades])
        running_max = np.maximum.accumulate(cumulative_pnl)
        drawdowns = (cumulative_pnl - running_max) / (running_max + 1e-6)
        max_dd = abs(drawdowns.min()) if len(drawdowns) > 0 else 0.0
        
        return {
            'total_trades': len(self.trades),
            'closed_trades': len(closed_trades),
            'open_trades': len(open_trades),
            'wins': wins,
            'losses': losses,
            'win_rate': wins / len(closed_trades) if closed_trades else 0.0,
            'total_pnl': total_pnl,
            'avg_pnl': total_pnl / len(closed_trades) if closed_trades else 0.0,
            'avg_pnl_pct': np.mean(pnl_values) if pnl_values else 0.0,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_dd
        }
    
    def save_session_report(self):
        """Save comprehensive session report"""
        summary = self.get_performance_summary()
        
        report = {
            'session_info': {
                'start_time': self.session_start.isoformat(),
                'end_time': datetime.now().isoformat(),
                'duration_hours': (datetime.now() - self.session_start).total_seconds() / 3600
            },
            'performance': summary,
            'trades': [asdict(t) for t in self.trades.values()],
            'signals': self.signal_history[-100:],  # Last 100 signals
            'prices': self.price_history[-100:]  # Last 100 prices
        }
        
        # Save JSON
        report_path = self.output_dir / f"session_{datetime.now():%Y%m%d_%H%M%S}.json"
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"Session report saved: {report_path}")
        
        # Save CSV of trades
        if self.trades:
            trades_df = pd.DataFrame([asdict(t) for t in self.trades.values()])
            csv_path = self.output_dir / f"trades_{datetime.now():%Y%m%d_%H%M%S}.csv"
            trades_df.to_csv(csv_path, index=False)
            logger.info(f"Trades CSV saved: {csv_path}")
        
        # Print summary
        print("\n" + "="*70)
        print("PAPER TRADING SESSION SUMMARY")
        print("="*70)
        print(f"Duration: {summary.get('total_trades', 0)} trades over {report['session_info']['duration_hours']:.1f} hours")
        print(f"Closed: {summary.get('closed_trades', 0)} | Open: {summary.get('open_trades', 0)}")
        print(f"Wins: {summary.get('wins', 0)} | Losses: {summary.get('losses', 0)}")
        print(f"Win Rate: {summary.get('win_rate', 0):.1%}")
        print(f"Total P&L: ${summary.get('total_pnl', 0):.2f}")
        print(f"Avg P&L per trade: ${summary.get('avg_pnl', 0):.2f}")
        print(f"Sharpe Ratio: {summary.get('sharpe_ratio', 0):.2f}")
        print(f"Max Drawdown: {summary.get('max_drawdown', 0):.2%}")
        print("="*70)
        
        return report
    
    def print_performance_snapshot(self):
        """Print current performance"""
        summary = self.get_performance_summary()
        
        print("\n" + "-"*50)
        print("PERFORMANCE SNAPSHOT")
        print(f"Time: {datetime.now():%Y-%m-%d %H:%M:%S}")
        print(f"Total trades: {summary['total_trades']} (closed: {summary['closed_trades']}, open: {summary['open_trades']})")
        print(f"Win rate: {summary['win_rate']:.1%} ({summary['wins']}/{summary['wins'] + summary['losses']})")
        print(f"P&L: ${summary['total_pnl']:.2f} (avg: ${summary['avg_pnl']:.2f})")
        print(f"Sharpe: {summary['sharpe_ratio']:.2f} | Max DD: {summary['max_drawdown']:.2%}")
        print("-"*50)


# Import numpy if needed
import numpy as np
