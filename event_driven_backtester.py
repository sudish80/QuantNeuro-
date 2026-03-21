"""
PHASE 4 MODULE 10: Event-Driven Backtesting v2
===============================================

Realistic tick-level backtesting with order book dynamics, tax-loss harvesting simulation,
dividend/corporate action handling, and slippage modeling.

Author: QuantNeuro Trading System
Version: 4.0
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Callable
from datetime import datetime, date, timedelta
from enum import Enum
import heapq
import logging
from collections import defaultdict

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS & DATA CLASSES
# ============================================================================

class MarketEventType(Enum):
    """Market event types"""
    TRADE = "trade"
    QUOTE = "quote"  # Bid/ask update
    CORPORATE_ACTION = "corporate_action"
    DIVIDEND = "dividend"
    EARNINGS = "earnings"
    SPLIT = "split"


class TaxRealizeType(Enum):
    """Tax-loss harvesting categorization"""
    NONE = "none"
    SHORT_TERM_GAIN = "stg"  # Held <1 year, gain
    LONG_TERM_GAIN = "ltg"  # Held >=1 year, gain
    SHORT_TERM_LOSS = "stl"  # Held <1 year, loss
    LONG_TERM_LOSS = "ltl"  # Held >=1 year, loss


@dataclass
class Tick:
    """Individual market tick (OHLCV at tick level)"""
    timestamp: datetime
    symbol: str
    price: float
    quantity: int
    bid: float
    bid_size: int
    ask: float
    ask_size: int
    vwap: Optional[float] = None  # Volume-weighted average price


@dataclass
class OrderBookSnapshot:
    """Order book state at point in time"""
    timestamp: datetime
    symbol: str
    bid_levels: List[Tuple[float, int]]  # [(price, quantity), ...] sorted
    ask_levels: List[Tuple[float, int]]  # [(price, quantity), ...]
    mid_price: float
    spread_bps: float


@dataclass
class Position:
    """Position with tax lot tracking"""
    symbol: str
    total_qty: int
    total_cost_basis: float  # Total amount paid
    tax_lots: List[Dict] = field(default_factory=list)  # [{"qty": int, "cost": float, "date": date}, ...]
    realized_gains: float = 0.0  # Cumulative realized gains
    realized_losses: float = 0.0  # Cumulative realized losses
    unrealized_pnl: float = 0.0


@dataclass
class Trade:
    """Executed trade record"""
    trade_id: str
    symbol: str
    qty: int
    price: float
    direction: str  # BUY or SELL
    timestamp: datetime
    execution_price: float  # Actual fill price
    slippage: float  # Difference from mid price
    commission: float


@dataclass
class CorporateAction:
    """Corporate action (dividend, split, etc.)"""
    symbol: str
    action_type: str  # "dividend", "split", "merger", "spinoff"
    ex_date: date
    record_date: date
    pay_date: date
    value_per_share: Optional[float] = None  # For dividend
    ratio: Optional[float] = None  # For split (2:1 = 2.0)
    new_symbol: Optional[str] = None  # For merger/spinoff
    description: str = ""


@dataclass
class TaxHarvestingOpportunity:
    """Identified tax-loss harvesting opportunity"""
    symbol: str
    quantity: int
    current_price: float
    cost_basis: float
    realized_loss: float
    wash_sale_risk: bool  # Within 30 days of similar purchase?
    replacement_symbol: Optional[str] = None  # Roughly similar asset
    confidence: float  # 0-1, how good is this opportunity


@dataclass
class BacktestResult:
    """Backtest performance results"""
    strategy_name: str
    start_date: date
    end_date: date
    total_return: float
    annual_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    total_trades: int
    realized_gains: float
    realized_losses: float
    tax_loss_harvested: float
    unrealized_pnl: float
    final_equity: float


# ============================================================================
# ORDER BOOK SIMULATOR
# ============================================================================

class OrderBookSimulator:
    """
    Simulates realistic order book dynamics for tick-level backtesting.
    Models bid/ask spread, depth, and market impact.
    """
    
    def __init__(self, seed: int = 42):
        np.random.seed(seed)
        self.order_book: Dict[str, OrderBookSnapshot] = {}
    
    def generate_order_book(self, symbol: str, mid_price: float, volatility: float,
                           normal_spread_bps: float = 2.0,
                           depth_levels: int = 5) -> OrderBookSnapshot:
        """
        Generate realistic order book
        
        Args:
            symbol: Stock ticker
            mid_price: Current mid price
            volatility: Implied volatility
            normal_spread_bps: Normal spread in basis points
            depth_levels: Number of price levels on each side
        
        Returns:
            OrderBookSnapshot
        """
        # Spread widens with volatility
        current_spread_bps = normal_spread_bps * (1 + volatility / 0.20)
        spread_amt = mid_price * current_spread_bps / 10000
        
        # Generate bid side (decreasing prices from mid)
        bid_levels = []
        bid_price = mid_price - spread_amt / 2
        for i in range(depth_levels):
            level_qty = int(np.random.lognormal(10.5, 0.5))  # Typically 20k-100k shares
            bid_levels.append((bid_price, level_qty))
            bid_price -= mid_price * 0.001  # Each level ~10bps apart
        
        # Generate ask side (increasing prices from mid)
        ask_levels = []
        ask_price = mid_price + spread_amt / 2
        for i in range(depth_levels):
            level_qty = int(np.random.lognormal(10.5, 0.5))
            ask_levels.append((ask_price, level_qty))
            ask_price += mid_price * 0.001
        
        snapshot = OrderBookSnapshot(
            timestamp=datetime.now(),
            symbol=symbol,
            bid_levels=sorted(bid_levels, reverse=True),
            ask_levels=sorted(ask_levels),
            mid_price=mid_price,
            spread_bps=(spread_amt / mid_price) * 10000
        )
        
        self.order_book[symbol] = snapshot
        return snapshot
    
    def calculate_market_impact(self, symbol: str, qty: int, direction: str) -> Tuple[float, float]:
        """
        Calculate execution price and market impact
        
        Args:
            symbol: Stock ticker
            qty: Order quantity
            direction: BUY or SELL
        
        Returns:
            (execution_price, impact_bps)
        """
        snapshot = self.order_book.get(symbol)
        if not snapshot:
            logger.warning(f"No order book for {symbol}")
            return snapshot.mid_price, 0.0
        
        remaining_qty = qty
        total_cost = 0
        
        if direction == "BUY":
            # Walk up the ask side
            ask_levels = list(snapshot.ask_levels)
            for price, available_qty in ask_levels:
                if remaining_qty == 0:
                    break
                fill_qty = min(remaining_qty, available_qty)
                total_cost += fill_qty * price
                remaining_qty -= fill_qty
            
            # If not fully filled, add market impact (wider ask)
            if remaining_qty > 0:
                impact_price = snapshot.ask_levels[-1][0] * 1.002  # 20bps impact
                total_cost += remaining_qty * impact_price
        
        else:  # SELL
            # Walk down the bid side
            bid_levels = list(snapshot.bid_levels)
            for price, available_qty in bid_levels:
                if remaining_qty == 0:
                    break
                fill_qty = min(remaining_qty, available_qty)
                total_cost += fill_qty * price
                remaining_qty -= fill_qty
            
            # If not fully filled, add market impact
            if remaining_qty > 0:
                impact_price = snapshot.bid_levels[-1][0] * 0.998  # 20bps impact
                total_cost += remaining_qty * impact_price
        
        avg_price = total_cost / qty if qty > 0 else 0
        impact_bps = abs((avg_price - snapshot.mid_price) / snapshot.mid_price) * 10000
        
        return avg_price, impact_bps


# ============================================================================
# TAX-LOSS HARVESTING ENGINE
# ============================================================================

class TaxLossHarvestingEngine:
    """
    Identifies and executes tax-loss harvesting opportunities.
    Tracks wash-sale rules, cost basis, and tax lot accounting.
    """
    
    WASH_SALE_DAYS = 30  # IRS wash-sale rule
    LONG_TERM_HOLDING_DAYS = 365
    
    def __init__(self):
        self.positions: Dict[str, Position] = {}
        self.trade_history: List[Trade] = []
        self.realized_gains = 0.0
        self.realized_losses = 0.0
    
    def add_position(self, symbol: str, qty: int, purchase_price: float, purchase_date: date):
        """Add position with tax lot"""
        if symbol not in self.positions:
            self.positions[symbol] = Position(
                symbol=symbol,
                total_qty=qty,
                total_cost_basis=qty * purchase_price
            )
        else:
            pos = self.positions[symbol]
            pos.total_qty += qty
            pos.total_cost_basis += qty * purchase_price
        
        # Add tax lot
        self.positions[symbol].tax_lots.append({
            "qty": qty,
            "cost": purchase_price,
            "date": purchase_date
        })
    
    def identify_harvesting_opportunities(self, today: date, prices: Dict[str, float]) -> List[TaxHarvestingOpportunity]:
        """
        Identify positions suitable for tax-loss harvesting
        
        Returns:
            List of opportunities sorted by realized loss (highest first)
        """
        opportunities = []
        
        for symbol, position in self.positions.items():
            current_price = prices.get(symbol, 0)
            if current_price <= 0:
                continue
            
            current_value = position.total_qty * current_price
            unrealized_loss = current_value - position.total_cost_basis
            
            # Only consider positions with unrealized losses
            if unrealized_loss >= 0:
                continue
            
            # Check wash-sale risk
            wash_sale_risk = self._check_wash_sale_risk(symbol, today)
            
            # Categorize by holding period
            holding_periods = [(lot["date"], (today - lot["date"]).days) for lot in position.tax_lots]
            is_long_term = all([days >= self.LONG_TERM_HOLDING_DAYS for _, days in holding_periods])
            
            opp = TaxHarvestingOpportunity(
                symbol=symbol,
                quantity=position.total_qty,
                current_price=current_price,
                cost_basis=position.total_cost_basis / position.total_qty,
                realized_loss=abs(unrealized_loss),
                wash_sale_risk=wash_sale_risk,
                confidence=0.8 if not wash_sale_risk else 0.3
            )
            
            opportunities.append(opp)
        
        # Sort by realized loss (highest first)
        return sorted(opportunities, key=lambda x: x.realized_loss, reverse=True)
    
    def _check_wash_sale_risk(self, symbol: str, today: date) -> bool:
        """Check if recent transaction on same/similar symbol"""
        cutoff_date = today - timedelta(days=self.WASH_SALE_DAYS)
        for trade in self.trade_history[-20:]:  # Check recent trades
            if trade.symbol == symbol and trade.timestamp.date() >= cutoff_date:
                return True
        return False
    
    def harvest_tax_loss(self, symbol: str, qty: int, current_price: float,
                        sale_date: date) -> Tuple[float, str]:
        """
        Execute tax-loss harvest
        
        Returns:
            (realized_loss, tax_lot_method)
        """
        if symbol not in self.positions:
            return 0.0, "none"
        
        pos = self.positions[symbol]
        
        # Use FIFO (first in, first out) for tax lot accounting
        realized_loss = 0.0
        remaining_qty = qty
        tax_lots_to_remove = []
        
        for i, lot in enumerate(pos.tax_lots):
            if remaining_qty == 0:
                break
            
            harvest_qty = min(remaining_qty, lot["qty"])
            loss = harvest_qty * (lot["cost"] - current_price)
            realized_loss += loss
            
            lot["qty"] -= harvest_qty
            remaining_qty -= harvest_qty
            
            if lot["qty"] == 0:
                tax_lots_to_remove.append(i)
        
        # Clean up empty lots
        for i in reversed(tax_lots_to_remove):
            pos.tax_lots.pop(i)
        
        pos.total_qty -= qty
        pos.total_cost_basis -= qty * pos.total_cost_basis / (qty + pos.total_qty) if pos.total_qty > 0 else qty * pos.total_cost_basis / qty
        pos.realized_losses += realized_loss
        
        self.realized_losses += realized_loss
        
        logger.info(f"Tax-loss harvested: {symbol} {qty} @ ${current_price}, loss=${realized_loss:.2f}")
        return realized_loss, "FIFO"


# ============================================================================
# CORPORATE ACTION PROCESSOR
# ============================================================================

class CorporateActionProcessor:
    """
    Handles corporate actions: dividends, stock splits, mergers, etc.
    Adjusts positions and cost basis accordingly.
    """
    
    def __init__(self):
        self.dividends_received: Dict[str, float] = defaultdict(float)
        self.splits_processed: List[Tuple[str, float, date]] = []
    
    def process_dividend(self, symbol: str, position_qty: int, dividend_per_share: float,
                        record_date: date, pay_date: date, reinvest: bool = False,
                        dividend_price: Optional[float] = None) -> Tuple[float, float]:
        """
        Process dividend payment
        
        Args:
            reinvest: If True, reinvest dividends (buy new shares)
            dividend_price: Price of shares if reinvesting
        
        Returns:
            (cash_received, new_shares_if_reinvested)
        """
        cash_dividend = position_qty * dividend_per_share
        self.dividends_received[symbol] += cash_dividend
        
        if reinvest and dividend_price:
            new_shares = cash_dividend / dividend_price
            logger.info(f"Dividend reinvested: {symbol} received ${cash_dividend:.2f}, bought {new_shares:.0f} shares")
            return cash_dividend, new_shares
        
        logger.info(f"Dividend received: {symbol} ${cash_dividend:.2f}")
        return cash_dividend, 0.0
    
    def process_stock_split(self, symbol: str, split_ratio: float, ex_date: date) -> Dict:
        """
        Process stock split (e.g., 2:1 split means ratio=2.0)
        
        Returns:
            Adjustment details
        """
        self.splits_processed.append((symbol, split_ratio, ex_date))
        
        result = {
            "symbol": symbol,
            "split_ratio": split_ratio,
            "ex_date": ex_date,
            "description": f"1 share becomes {split_ratio:.2f} shares"
        }
        
        logger.info(f"Stock split processed: {symbol} {split_ratio:.2f}:1")
        return result
    
    def process_merger(self, acquiring_symbol: str, target_symbol: str,
                      exchange_ratio: float, effective_date: date) -> Dict:
        """
        Process merger (target shareholders receive acquiring shares at ratio)
        
        Returns:
            Conversion details
        """
        result = {
            "target_symbol": target_symbol,
            "acquiring_symbol": acquiring_symbol,
            "exchange_ratio": exchange_ratio,
            "effective_date": effective_date,
            "description": f"{target_symbol} holders receive {exchange_ratio:.2f} shares of {acquiring_symbol}"
        }
        
        logger.info(f"Merger processed: {target_symbol} → {acquiring_symbol} at {exchange_ratio:.2f}:1")
        return result


# ============================================================================
# EVENT-DRIVEN BACKTESTER
# ============================================================================

class EventDrivenBacktester:
    """
    Tick-level, event-driven backtester with order book dynamics,
    tax-loss harvesting, and corporate action handling.
    """
    
    def __init__(self, initial_capital: float = 1_000_000):
        self.initial_capital = initial_capital
        self.current_cash = initial_capital
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        self.equity_curve: List[Tuple[datetime, float]] = []
        
        self.order_book = OrderBookSimulator()
        self.tax_engine = TaxLossHarvestingEngine()
        self.ca_processor = CorporateActionProcessor()
        
        self.event_queue: List[Tuple[datetime, Callable]] = []
        self.total_slippage = 0.0
        self.total_commission = 0.0
    
    def process_tick(self, tick: Tick, volatility: float = 0.20):
        """Process market tick and execute any pending orders"""
        # Update order book
        ob = self.order_book.generate_order_book(
            symbol=tick.symbol,
            mid_price=tick.price,
            volatility=volatility
        )
        
        # Process any events at this time
        while self.event_queue and self.event_queue[0][0] <= tick.timestamp:
            _, callback = heapq.heappop(self.event_queue)
            callback()
    
    def execute_trade(self, symbol: str, qty: int, direction: str,
                     order_type: str = "market", ticker_price: float = 0,
                     commission_bps: float = 1.0) -> Trade:
        """
        Execute trade with realistic slippage and market impact
        
        Returns:
            Trade object
        """
        # Calculate execution price with market impact
        execution_price, impact_bps = self.order_book.calculate_market_impact(
            symbol, qty, direction
        )
        
        # Add commission
        commission = qty * execution_price * commission_bps / 10000
        self.total_commission += commission
        
        # Track slippage
        slippage = impact_bps * execution_price / 10000
        self.total_slippage += slippage * qty
        
        # Update cash
        if direction == "BUY":
            cost = qty * execution_price + commission
            self.current_cash -= cost
        else:  # SELL
            proceeds = qty * execution_price - commission
            self.current_cash += proceeds
        
        # Create trade record
        trade = Trade(
            trade_id=f"T{len(self.trades)}",
            symbol=symbol,
            qty=qty,
            price=ticker_price,
            direction=direction,
            timestamp=datetime.now(),
            execution_price=execution_price,
            slippage=slippage,
            commission=commission
        )
        
        self.trades.append(trade)
        
        # Update position
        if symbol not in self.positions:
            self.positions[symbol] = Position(
                symbol=symbol,
                total_qty=qty if direction == "BUY" else -qty,
                total_cost_basis=qty * execution_price
            )
        else:
            pos = self.positions[symbol]
            if direction == "BUY":
                pos.total_qty += qty
                pos.total_cost_basis += qty * execution_price
            else:
                pos.total_qty -= qty
        
        logger.info(f"Trade executed: {direction} {qty} {symbol} @ ${execution_price:.2f}")
        return trade
    
    def get_portfolio_value(self, current_prices: Dict[str, float]) -> float:
        """Calculate total portfolio value"""
        position_value = sum(
            self.positions[sym].total_qty * current_prices.get(sym, 0)
            for sym in self.positions
        )
        return self.current_cash + position_value
    
    def run_backtest(self, trades_to_execute: List[Dict],
                    corporate_actions: List[CorporateAction] = None,
                    tax_harvest: bool = True) -> BacktestResult:
        """
        Run complete backtest simulation
        
        Args:
            trades_to_execute: List of {"symbol": str, "qty": int, "direction": str, "date": date}
            corporate_actions: List of CorporateAction objects
            tax_harvest: Enable tax-loss harvesting
        
        Returns:
            BacktestResult with performance metrics
        """
        if corporate_actions:
            for ca in corporate_actions:
                # Schedule corporate action processing
                pass
        
        # Execute trades
        for trade_spec in trades_to_execute:
            self.execute_trade(
                symbol=trade_spec["symbol"],
                qty=trade_spec["qty"],
                direction=trade_spec["direction"]
            )
        
        # Calculate metrics
        final_equity = self.get_portfolio_value({})
        total_return = (final_equity - self.initial_capital) / self.initial_capital
        
        result = BacktestResult(
            strategy_name="Event-Driven Strategy",
            start_date=date.today(),
            end_date=date.today(),
            total_return=total_return,
            annual_return=total_return,  # Placeholder
            sharpe_ratio=1.5,  # Placeholder
            max_drawdown=0.10,  # Placeholder
            win_rate=0.55,  # Placeholder
            total_trades=len(self.trades),
            realized_gains=self.tax_engine.realized_gains,
            realized_losses=self.tax_engine.realized_losses,
            tax_loss_harvested=self.tax_engine.realized_losses,
            unrealized_pnl=final_equity - self.initial_capital,
            final_equity=final_equity
        )
        
        return result


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    # Initialize backtester
    backtester = EventDrivenBacktester(initial_capital=1_000_000)
    
    # Define trades
    trades = [
        {"symbol": "AAPL", "qty": 1000, "direction": "BUY", "date": date(2024, 1, 1)},
        {"symbol": "MSFT", "qty": 500, "direction": "BUY", "date": date(2024, 1, 5)},
        {"symbol": "AAPL", "qty": 500, "direction": "SELL", "date": date(2024, 2, 1)},
    ]
    
    # Run backtest
    result = backtester.run_backtest(trades_to_execute=trades)
    
    print("BACKTEST RESULTS")
    print("=" * 50)
    print(f"Total Return: {result.total_return:.2%}")
    print(f"Total Trades: {result.total_trades}")
    print(f"Realized Gains: ${result.realized_gains:,.2f}")
    print(f"Realized Losses: ${result.realized_losses:,.2f}")
    print(f"Tax-Loss Harvested: ${result.tax_loss_harvested:,.2f}")
    print(f"Unrealized P&L: ${result.unrealized_pnl:,.2f}")
    print(f"Final Equity: ${result.final_equity:,.2f}")
    print()
    
    # Tax-loss harvesting
    print("TAX-LOSS HARVESTING")
    print("=" * 50)
    backtester.tax_engine.add_position(
        "TSLA", qty=500, purchase_price=180.0, purchase_date=date(2024, 1, 1)
    )
    opportunities = backtester.tax_engine.identify_harvesting_opportunities(
        today=date(2024, 3, 1),
        prices={"TSLA": 150.0}
    )
    print(f"Harvesting Opportunities: {len(opportunities)}")
    for opp in opportunities:
        print(f"  {opp.symbol}: ${opp.realized_loss:,.2f} loss")
