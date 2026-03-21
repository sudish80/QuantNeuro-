"""
MOCK TRADER - Phase 4 Testing Module

Simulates live trading environment for testing without real broker connectivity.

Features:
- Realistic order execution with fills/partial fills
- Slippage and commission simulation
- Market data feed simulation
- Account state tracking
- Error scenarios

Usage:
    trader = MockTrader(initial_capital=1000000)
    trader.place_order("AAPL", 100, 150.5, OrderType.LIMIT, OrderSide.BUY)
    
    for position in trader.get_positions():
        print(f"{position.ticker}: {position.qty} shares")
    
    metrics = trader.get_daily_metrics()
    print(f"Daily PnL: ${metrics['daily_pnl']}")
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
from enum import Enum
import random
import numpy as np

from broker_adapter import (
    BrokerAdapter, Order, Position, Account, Trade,
    OrderType, OrderSide, OrderStatus, PositionStatus,
    ConnectionStatus
)


# ============================================================================
# MOCK DATA GENERATORS
# ============================================================================

class MarketDataSimulator:
    """Generates realistic market data for testing."""
    
    def __init__(self, seed: int = 42):
        np.random.seed(seed)
        self.prices: Dict[str, List[float]] = {}
        self.base_prices = {
            "AAPL": 150.0,
            "GOOGL": 130.0,
            "MSFT": 300.0,
            "TSLA": 250.0,
            "AMZN": 180.0,
        }
    
    def get_price(self, ticker: str, time_step: int = 0) -> float:
        """
        Get simulated price at time step.
        
        Simulates random walk with drift.
        """
        if ticker not in self.prices:
            self.prices[ticker] = []
        
        base = self.base_prices.get(ticker, 100.0)
        
        # Random walk: price(t) = price(t-1) * (1 + daily_return)
        if time_step == 0:
            price = base + np.random.normal(0, 1)  # Initial noise
        else:
            prev_price = self.get_price(ticker, time_step - 1)
            daily_return = np.random.normal(0.0005, 0.02)  # 5bps mean, 2% vol
            price = prev_price * (1 + daily_return)
        
        return max(0.01, price)  # Prevent zero/negative prices
    
    def get_bid_ask(
        self, ticker: str, time_step: int = 0
    ) -> tuple:
        """Get bid/ask spread."""
        mid = self.get_price(ticker, time_step)
        spread = mid * 0.0005  # 5 bps spread
        return (mid - spread/2, mid + spread/2)


# ============================================================================
# MOCK TRADER
# ============================================================================

class MockTrader(BrokerAdapter):
    """
    Mock trading environment for backtesting and unit testing.
    
    Simulates realistic market conditions including:
    - Slippage based on order size
    - Commission
    - Partial fills
    - Market data (bid/ask)
    - Position tracking
    """
    
    def __init__(
        self,
        initial_capital: float = 1000000,
        commission_pct: float = 0.001,  # 10 bps
        slippage_bps: float = 1.5,
        seed: int = 42
    ):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: Dict[str, Position] = {}
        self.orders: Dict[str, Order] = {}
        self.trades: List[Trade] = []
        
        self.commission_pct = commission_pct
        self.slippage_bps = slippage_bps
        
        self.connection_status = ConnectionStatus.DISCONNECTED
        self.last_error = None
        
        self.market_data = MarketDataSimulator(seed)
        self.time_step = 0
        self.order_id_counter = 1
        self.trade_id_counter = 1
    
    # ========== CONNECTION ==========
    
    def connect(self) -> bool:
        """Connect mock trader."""
        self.connection_status = ConnectionStatus.CONNECTED
        return True
    
    def disconnect(self) -> bool:
        """Disconnect mock trader."""
        self.connection_status = ConnectionStatus.DISCONNECTED
        return True
    
    def get_connection_status(self) -> ConnectionStatus:
        """Get connection status."""
        return self.connection_status
    
    # ========== ACCOUNT ==========
    
    def get_account(self) -> Account:
        """Get account information."""
        total_position_value = sum(
            pos.qty * pos.current_price for pos in self.positions.values()
        )
        equity = self.cash + total_position_value
        leverage = (self.cash + total_position_value) / max(equity, 0.01)
        
        return Account(
            account_id="MOCK-123456",
            cash=self.cash,
            buying_power=self.cash,
            equity=equity,
            positions_value=total_position_value,
            leverage=leverage,
            margin_available=self.cash * 3  # 3x margin
        )
    
    def get_buying_power(self) -> float:
        """Get available buying power."""
        return self.cash
    
    # ========== POSITIONS ==========
    
    def get_positions(self) -> List[Position]:
        """Get all open positions."""
        return list(self.positions.values())
    
    def get_position(self, ticker: str) -> Optional[Position]:
        """Get specific position."""
        return self.positions.get(ticker)
    
    # ========== ORDERS ==========
    
    def place_order(
        self,
        ticker: str,
        qty: int,
        price: float,
        order_type: OrderType,
        side: OrderSide,
        stop_price: Optional[float] = None,
        duration: Optional[int] = None
    ) -> Order:
        """Place order."""
        order_id = str(self.order_id_counter)
        self.order_id_counter += 1
        
        order = Order(
            order_id=order_id,
            ticker=ticker,
            qty=qty,
            price=price,
            order_type=order_type,
            side=side,
            status=OrderStatus.SUBMITTED
        )
        
        self.orders[order_id] = order
        
        # Simulate immediate execution
        self._execute_order(order)
        
        return order
    
    def _execute_order(self, order: Order):
        """Simulate order execution."""
        current_price = self.market_data.get_price(order.ticker, self.time_step)
        
        # Apply slippage
        slippage_multiplier = 1 + (self.slippage_bps / 10000)
        if order.side == OrderSide.BUY:
            execution_price = current_price * slippage_multiplier
        else:  # SELL
            execution_price = current_price / slippage_multiplier
        
        # Apply partial fill probability (80% chance of full fill)
        if random.random() < 0.8:
            filled_qty = order.qty
        else:
            filled_qty = int(order.qty * random.uniform(0.5, 0.99))
        
        # Calculate costs
        gross_cost = filled_qty * execution_price
        commission = gross_cost * self.commission_pct
        
        # Update account
        if order.side == OrderSide.BUY:
            self.cash -= (gross_cost + commission)
            new_qty = self.positions.get(order.ticker, Position(
                ticker=order.ticker,
                qty=0,
                avg_cost=0,
                current_price=execution_price,
                unrealized_pnl=0,
                unrealized_pnl_pct=0
            )).qty + filled_qty
            
            # Update position
            old_cost = self.positions.get(order.ticker, Position(
                ticker=order.ticker, qty=0, avg_cost=execution_price,
                current_price=execution_price, unrealized_pnl=0, unrealized_pnl_pct=0
            )).avg_cost if order.ticker in self.positions else execution_price
            
            avg_cost = (old_cost * (new_qty - filled_qty) + execution_price * filled_qty) / new_qty
            
            position = Position(
                ticker=order.ticker,
                qty=new_qty,
                avg_cost=avg_cost,
                current_price=execution_price,
                unrealized_pnl=new_qty * (execution_price - avg_cost),
                unrealized_pnl_pct=(execution_price - avg_cost) / avg_cost if avg_cost else 0
            )
        else:  # SELL
            self.cash += (gross_cost - commission)
            new_qty = self.positions.get(order.ticker, Position(
                ticker=order.ticker, qty=0, avg_cost=0,
                current_price=execution_price, unrealized_pnl=0, unrealized_pnl_pct=0
            )).qty - filled_qty
            
            avg_cost = self.positions[order.ticker].avg_cost if order.ticker in self.positions else execution_price
            
            position = Position(
                ticker=order.ticker,
                qty=max(0, new_qty),
                avg_cost=avg_cost,
                current_price=execution_price,
                unrealized_pnl=max(0, new_qty) * (execution_price - avg_cost),
                unrealized_pnl_pct=(execution_price - avg_cost) / avg_cost if avg_cost else 0,
                status=PositionStatus.CLOSED if new_qty <= 0 else PositionStatus.OPEN
            )
        
        if position.qty > 0:
            self.positions[order.ticker] = position
        elif order.ticker in self.positions:
            del self.positions[order.ticker]
        
        # Update order
        order.filled_qty = filled_qty
        order.avg_fill_price = execution_price
        order.commission = commission
        order.status = OrderStatus.FILLED if filled_qty == order.qty else OrderStatus.PARTIAL
        
        # Record trade
        trade = Trade(
            trade_id=str(self.trade_id_counter),
            ticker=order.ticker,
            qty=filled_qty,
            price=execution_price,
            side=order.side,
            commission=commission,
            executed_at=datetime.utcnow(),
            order_id=order.order_id
        )
        self.trades.append(trade)
        self.trade_id_counter += 1
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel order."""
        if order_id in self.orders:
            order = self.orders[order_id]
            if order.status in [OrderStatus.PENDING, OrderStatus.SUBMITTED]:
                order.status = OrderStatus.CANCELLED
                return True
        return False
    
    def get_order_status(self, order_id: str) -> OrderStatus:
        """Get order status."""
        if order_id in self.orders:
            return self.orders[order_id].status
        return OrderStatus.REJECTED
    
    def get_orders(self, status: Optional[OrderStatus] = None) -> List[Order]:
        """Get orders."""
        if status is None:
            return list(self.orders.values())
        return [o for o in self.orders.values() if o.status == status]
    
    # ========== FILLS & TRADES ==========
    
    def get_trades(self) -> List[Trade]:
        """Get trades."""
        return list(self.trades)
    
    def get_fills(self, order_id: str) -> List[Dict]:
        """Get fills for order."""
        fills = []
        for trade in self.trades:
            if trade.order_id == order_id:
                fills.append({
                    "qty": trade.qty,
                    "price": trade.price,
                    "timestamp": trade.executed_at
                })
        return fills
    
    # ========== MARKET DATA ==========
    
    def get_last_price(self, ticker: str) -> float:
        """Get last price."""
        return self.market_data.get_price(ticker, self.time_step)
    
    def get_bid_ask(self, ticker: str) -> tuple:
        """Get bid/ask."""
        return self.market_data.get_bid_ask(ticker, self.time_step)
    
    # ========== ERROR HANDLING ==========
    
    def get_last_error(self) -> Optional[str]:
        """Get last error."""
        return self.last_error
    
    def clear_error(self):
        """Clear error."""
        self.last_error = None
    
    # ========== METRICS ==========
    
    def get_daily_metrics(self) -> Dict:
        """Get daily trading metrics."""
        account = self.get_account()
        
        daily_return = 0
        if self.initial_capital > 0:
            daily_return = (account.equity - self.initial_capital) / self.initial_capital
        
        daily_trades = [t for t in self.trades if t.executed_at.date() == datetime.utcnow().date()]
        daily_pnl = sum(t.qty * (t.price if t.side == OrderSide.SELL else -t.price) 
                       for t in daily_trades)
        
        return {
            "equity": account.equity,
            "cash": account.cash,
            "daily_pnl": daily_pnl,
            "daily_return": daily_return,
            "leverage": account.leverage,
            "positions_count": len(self.positions),
            "trades_count": len(daily_trades)
        }
    
    def advance_time(self, steps: int = 1):
        """Advance simulation time by N steps."""
        self.time_step += steps
        
        # Update position prices
        for ticker in self.positions:
            new_price = self.market_data.get_price(ticker, self.time_step)
            pos = self.positions[ticker]
            pos.current_price = new_price
            pos.unrealized_pnl = pos.qty * (new_price - pos.avg_cost)
            pos.unrealized_pnl_pct = (new_price - pos.avg_cost) / pos.avg_cost if pos.avg_cost else 0


# ============================================================================
# USAGE EXAMPLE
# ============================================================================

if __name__ == "__main__":
    print("Mock Trader - Testing Environment")
    print("=" * 60)
    
    trader = MockTrader(initial_capital=1000000)
    trader.connect()
    
    print(f"\nInitial Account:")
    account = trader.get_account()
    print(f"  Equity: ${account.equity:,.0f}")
    print(f"  Cash: ${account.cash:,.0f}")
    
    print(f"\nPlacing orders...")
    order1 = trader.place_order("AAPL", 100, 150.0, OrderType.LIMIT, OrderSide.BUY)
    order2 = trader.place_order("GOOGL", 50, 130.0, OrderType.LIMIT, OrderSide.BUY)
    
    print(f"\nPositions:")
    for pos in trader.get_positions():
        print(f"  {pos.ticker}: {pos.qty} shares @ ${pos.avg_cost:.2f}")
    
    print(f"\nDaily Metrics:")
    metrics = trader.get_daily_metrics()
    for k, v in metrics.items():
        if isinstance(v, float):
            print(f"  {k}: {v:,.2f}")
        else:
            print(f"  {k}: {v}")
    
    print("=" * 60)
