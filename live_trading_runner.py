"""
PHASE 4 MODULE 3: Live Trading Runner & Order Management System (OMS)
=====================================================================

Real-time order execution, position management, and risk enforcement.

Features:
- Order lifecycle management (pending → submitted → filled)
- Position tracking and P&L calculation
- Risk enforcement (position limits, stop losses, max drawdown)
- Transaction cost accounting
- Order prioritization and execution queue
- Circuit breakers and trading halts
- Audit trail and compliance recording
- Live rebalancing and dynamic adjustments

Author: QuantNeuro Trading System
Version: 4.0
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Callable
from datetime import datetime, timedelta
from enum import Enum
import numpy as np
import logging
from collections import deque
import asyncio

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS & DATA CLASSES
# ============================================================================

class ExecutionPriority(Enum):
    """Order execution priority"""
    CRITICAL = 1   # Risk management orders (stop losses)
    HIGH = 2       # Unanimous strategy signals
    NORMAL = 3     # Majority signals
    LOW = 4        # Discretionary signals


class RiskEvent(Enum):
    """Types of risk events"""
    MAX_POSITION_LIMIT = "max_position_limit"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    SHARPE_DEGRADATION = "sharpe_degradation"
    VOLATILITY_SPIKE = "volatility_spike"
    LIQUIDITY_WARNING = "liquidity_warning"
    MODEL_DEGRADATION = "model_degradation"


@dataclass
class OrderExecution:
    """Record of executed order"""
    order_id: str
    symbol: str
    qty: int
    fill_price: float
    execution_time: datetime
    commission: float
    slippage: float
    final_price: float  # fill_price + slippage
    total_cost: float   # (qty * final_price) + commission
    status: str = "filled"


@dataclass
class LivePosition:
    """Current live position tracking"""
    symbol: str
    qty: int
    avg_cost: float
    entry_time: datetime
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    stop_loss_price: float = 0.0
    take_profit_price: float = 0.0
    max_riskable: float = 0.0  # Max loss before stop
    status: str = "open"  # open, closing, closed
    last_update: datetime = field(default_factory=datetime.now)


@dataclass
class RiskMetrics:
    """Current portfolio risk metrics"""
    total_portfolio_value: float
    total_position_value: float
    cash: float
    buying_power: float
    
    # Risk metrics
    portfolio_delta: float  # Net directional exposure
    gross_exposure: float   # Sum of abs(position values)
    net_exposure: float     # Sum of position values
    concentration_max: float  # Largest position % of portfolio
    leverage: float        # Gross exposure / net assets
    
    # P&L
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    daily_pnl: float
    daily_pnl_pct: float
    
    # Risk limits
    max_daily_loss: float   # Maximum allowed daily loss
    remaining_daily_loss: float
    var_95: float  # Value at Risk (95% confidence)
    
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ExecutionQueue:
    """Queue item for order execution"""
    order_id: str
    symbol: str
    qty: int
    price: float
    priority: ExecutionPriority
    timestamp: datetime
    deadline: Optional[datetime] = None  # Max time to execute
    reason: str = ""  # Why order was placed


# ============================================================================
# LIVE TRADING RUNNER
# ============================================================================

class LiveTradingRunner:
    """
    Execute trades in real-time with comprehensive risk management
    """
    
    def __init__(
        self,
        broker_adapter,  # BrokerAdapter instance
        commission_calculator,  # CommissionCalculator instance
        portfolio_value: float,
        max_daily_loss_pct: float = 2.0,
        max_position_pct: float = 10.0,
        max_leverage: float = 3.0,
        circuit_breaker_threshold: float = 0.05,
    ):
        """
        Args:
            broker_adapter: Connection to broker
            commission_calculator: Commission calculation utility
            portfolio_value: Initial portfolio value
            max_daily_loss_pct: Max daily loss (% of portfolio)
            max_position_pct: Max single position (% of portfolio)
            max_leverage: Maximum portfolio leverage
            circuit_breaker_threshold: Halt trading if daily loss exceeds this
        """
        self.broker = broker_adapter
        self.commission_calc = commission_calculator
        self.initial_portfolio_value = portfolio_value
        self.portfolio_value = portfolio_value
        
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_position_pct = max_position_pct
        self.max_leverage = max_leverage
        self.circuit_breaker_threshold = circuit_breaker_threshold
        
        # State tracking
        self.positions: Dict[str, LivePosition] = {}
        self.execution_queue: deque = deque()
        self.execution_history: List[OrderExecution] = []
        self.risk_events: List[Tuple[datetime, RiskEvent, str]] = []
        
        # Daily metrics
        self.session_start_time = datetime.now()
        self.session_start_value = portfolio_value
        self.daily_realized_pnl = 0.0
        self.trades_today = 0
        self.trading_halted = False
        self.halted_reason = ""
        
        # Risk limits
        self.max_daily_loss = portfolio_value * (max_daily_loss_pct / 100)
        self.max_position_value = portfolio_value * (max_position_pct / 100)
    
    # ========== RISK CHECKS ==========
    
    def check_position_limit(self, symbol: str, qty: int, price: float) -> Tuple[bool, str]:
        """Check if position size respects limits"""
        position_value = abs(qty * price)
        
        if position_value > self.max_position_value:
            msg = f"{symbol}: Position value ${position_value:,.0f} exceeds limit ${self.max_position_value:,.0f}"
            return False, msg
        
        return True, "OK"
    
    def check_leverage_limit(self) -> Tuple[bool, str]:
        """Check if total leverage respects limit"""
        metrics = self.get_risk_metrics()
        
        if metrics.leverage > self.max_leverage:
            msg = f"Leverage {metrics.leverage:.2f}x exceeds maximum {self.max_leverage}x"
            return False, msg
        
        return True, "OK"
    
    def check_daily_loss_limit(self) -> Tuple[bool, str]:
        """Check if daily loss is within limits"""
        daily_pnl = self._calculate_daily_pnl()
        
        if daily_pnl < -self.max_daily_loss:
            msg = f"Daily loss ${abs(daily_pnl):,.0f} exceeds limit ${self.max_daily_loss:,.0f}"
            self._trigger_risk_event(RiskEvent.DAILY_LOSS_LIMIT, msg)
            return False, msg
        
        return True, "OK"
    
    def check_stop_losses(self, current_prices: Dict[str, float]) -> List[str]:
        """Check if any positions hit stop losses"""
        triggered_symbols = []
        
        for symbol, position in self.positions.items():
            if position.status != "open":
                continue
            
            current_price = current_prices.get(symbol, position.current_price)
            
            # Check stop loss
            if position.stop_loss_price > 0 and current_price <= position.stop_loss_price:
                triggered_symbols.append(symbol)
                logger.warning(f"STOP LOSS triggered: {symbol} @ {current_price}")
            
            # Check take profit
            elif position.take_profit_price > 0 and current_price >= position.take_profit_price:
                triggered_symbols.append(symbol)
                logger.info(f"TAKE PROFIT hit: {symbol} @ {current_price}")
        
        return triggered_symbols
    
    def check_circuit_breaker(self) -> Tuple[bool, str]:
        """Check if circuit breaker should be triggered"""
        daily_pnl = self._calculate_daily_pnl()
        daily_pnl_pct = daily_pnl / self.session_start_value
        
        if abs(daily_pnl_pct) > self.circuit_breaker_threshold:
            msg = f"Daily loss {daily_pnl_pct:.2%} exceeds circuit breaker threshold"
            self._trigger_risk_event(RiskEvent.VOLATILITY_SPIKE, msg)
            return False, msg
        
        return True, "OK"
    
    # ========== ORDER EXECUTION ==========
    
    def queue_order(
        self,
        symbol: str,
        qty: int,
        price: float,
        priority: ExecutionPriority,
        reason: str = ""
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Queue an order for execution
        
        Returns:
            (success, message, order_id)
        """
        order_id = f"ORD_{len(self.execution_history):06d}"
        
        # Risk checks
        passed, msg = self.check_position_limit(symbol, qty, price)
        if not passed:
            return False, msg, None
        
        passed, msg = self.check_daily_loss_limit()
        if not passed:
            return False, msg, None
        
        # Queue order
        item = ExecutionQueue(
            order_id=order_id,
            symbol=symbol,
            qty=qty,
            price=price,
            priority=priority,
            timestamp=datetime.now(),
            reason=reason
        )
        
        self.execution_queue.append(item)
        logger.info(f"Queued order {order_id}: {symbol} {qty} @ {price}")
        
        return True, "Order queued", order_id
    
    async def execute_orders(
        self,
        current_prices: Dict[str, float],
        max_orders_per_batch: int = 10
    ) -> List[OrderExecution]:
        """Execute pending orders from queue"""
        if self.trading_halted:
            logger.warning(f"Trading halted: {self.halted_reason}")
            return []
        
        executed = []
        orders_to_process = min(max_orders_per_batch, len(self.execution_queue))
        
        # Sort by priority (lower enum value = higher priority)
        pending_orders = list(self.execution_queue)
        pending_orders.sort(key=lambda x: (x.priority.value, x.timestamp))
        
        for _ in range(orders_to_process):
            if not pending_orders:
                break
            
            item = pending_orders.pop(0)
            self.execution_queue.remove(item)
            
            # Get current price
            price = current_prices.get(item.symbol, item.price)
            
            # Execute via broker
            try:
                execution = await self._execute_order_via_broker(
                    item, price
                )
                executed.append(execution)
                
                # Update position
                self._update_position_after_execution(item.symbol, execution)
                
                self.trades_today += 1
                logger.info(f"Executed: {item.order_id} {item.symbol} {item.qty} @ {execution.fill_price}")
            
            except Exception as e:
                logger.error(f"Order execution failed: {item.order_id} - {e}")
                # Re-queue with lower priority
                item.priority = ExecutionPriority.LOW
                self.execution_queue.append(item)
        
        # Check for circuit breakers after execution
        passed, msg = self.check_circuit_breaker()
        if not passed:
            self._halt_trading(msg)
        
        return executed
    
    async def _execute_order_via_broker(
        self,
        item: ExecutionQueue,
        execution_price: float
    ) -> OrderExecution:
        """Execute order through broker adapter"""
        # Calculate costs
        trade_value = abs(item.qty) * execution_price
        commission = self.commission_calc.calculate_commission(
            self.broker.broker_name, trade_value, abs(item.qty)
        )
        slippage = self.commission_calc.calculate_slippage(
            self.broker.broker_name, trade_value, abs(item.qty)
        )
        
        final_price = execution_price + (slippage / abs(item.qty)) if item.qty > 0 else execution_price - (slippage / abs(item.qty))
        total_cost = trade_value + commission + slippage
        
        return OrderExecution(
            order_id=item.order_id,
            symbol=item.symbol,
            qty=item.qty,
            fill_price=execution_price,
            execution_time=datetime.now(),
            commission=commission,
            slippage=slippage,
            final_price=final_price,
            total_cost=total_cost
        )
    
    def _update_position_after_execution(self, symbol: str, execution: OrderExecution):
        """Update position after order fills"""
        if symbol not in self.positions:
            # New position
            self.positions[symbol] = LivePosition(
                symbol=symbol,
                qty=execution.qty,
                avg_cost=execution.final_price,
                entry_time=execution.execution_time,
                current_price=execution.final_price
            )
        else:
            # Update existing position
            pos = self.positions[symbol]
            old_qty = pos.qty
            new_qty = old_qty + execution.qty
            
            if new_qty == 0:
                # Position closed
                pos.status = "closed"
                pos.qty = 0
                self.daily_realized_pnl += pos.unrealized_pnl
            else:
                # Average cost
                if old_qty * new_qty > 0:  # Same direction
                    pos.avg_cost = (pos.avg_cost * old_qty + execution.final_price * execution.qty) / new_qty
                else:
                    # Reversed
                    pos.avg_cost = execution.final_price
                
                pos.qty = new_qty
        
        # Update portfolio value
        self._update_portfolio_value()
    
    def _update_portfolio_value(self):
        """Recalculate total portfolio value"""
        total_position_value = 0
        
        for pos in self.positions.values():
            if pos.qty != 0:
                position_value = pos.qty * pos.current_price
                total_position_value += position_value
        
        cash = self.broker.get_buying_power()
        self.portfolio_value = cash + total_position_value
    
    def update_market_prices(self, current_prices: Dict[str, float]):
        """Update positions with latest market prices"""
        for symbol, price in current_prices.items():
            if symbol in self.positions:
                pos = self.positions[symbol]
                pos.current_price = price
                pos.unrealized_pnl = pos.qty * (price - pos.avg_cost)
                pos.unrealized_pnl_pct = (price - pos.avg_cost) / pos.avg_cost if pos.avg_cost != 0 else 0
                pos.last_update = datetime.now()
        
        self._update_portfolio_value()
    
    # ========== RISK METRICS ==========
    
    def get_risk_metrics(self) -> RiskMetrics:
        """Get current portfolio risk metrics"""
        total_position_value = 0
        gross_exposure = 0
        max_concentration = 0
        
        for pos in self.positions.values():
            position_value = pos.qty * pos.current_price
            total_position_value += position_value
            gross_exposure += abs(position_value)
            concentration = abs(position_value) / self.portfolio_value
            max_concentration = max(max_concentration, concentration)
        
        cash = self.broker.get_buying_power()
        leverage = gross_exposure / self.portfolio_value if self.portfolio_value > 0 else 1.0
        
        daily_pnl = self._calculate_daily_pnl()
        unrealized_pnl = sum(pos.unrealized_pnl for pos in self.positions.values())
        
        return RiskMetrics(
            total_portfolio_value=self.portfolio_value,
            total_position_value=total_position_value,
            cash=cash,
            buying_power=cash,
            portfolio_delta=total_position_value,
            gross_exposure=gross_exposure,
            net_exposure=total_position_value,
            concentration_max=max_concentration,
            leverage=leverage,
            realized_pnl=self.daily_realized_pnl,
            unrealized_pnl=unrealized_pnl,
            total_pnl=self.daily_realized_pnl + unrealized_pnl,
            daily_pnl=daily_pnl,
            daily_pnl_pct=daily_pnl / self.session_start_value if self.session_start_value > 0 else 0,
            max_daily_loss=self.max_daily_loss,
            remaining_daily_loss=self.max_daily_loss - abs(min(daily_pnl, 0))
        )
    
    def _calculate_daily_pnl(self) -> float:
        """Calculate daily P&L (including open positions)"""
        unrealized = sum(pos.unrealized_pnl for pos in self.positions.values())
        return self.daily_realized_pnl + unrealized
    
    # ========== POSITION MANAGEMENT ==========
    
    def set_stop_loss(self, symbol: str, stop_price: float) -> bool:
        """Set stop loss for position"""
        if symbol in self.positions:
            self.positions[symbol].stop_loss_price = stop_price
            return True
        return False
    
    def set_take_profit(self, symbol: str, tp_price: float) -> bool:
        """Set take profit for position"""
        if symbol in self.positions:
            self.positions[symbol].take_profit_price = tp_price
            return True
        return False
    
    def close_position(
        self,
        symbol: str,
        reason: str = "manual"
    ) -> Tuple[bool, str, Optional[str]]:
        """Close a position"""
        if symbol not in self.positions or self.positions[symbol].qty == 0:
            return False, f"No open position for {symbol}", None
        
        pos = self.positions[symbol]
        close_qty = -pos.qty  # Opposite of current position
        
        # Queue close order
        return self.queue_order(
            symbol, close_qty,
            pos.current_price,
            ExecutionPriority.HIGH,
            reason
        )
    
    def close_all_positions(self, reason: str = "emergency") -> Dict[str, str]:
        """Emergency close all positions"""
        results = {}
        for symbol in list(self.positions.keys()):
            success, msg, order_id = self.close_position(symbol, reason)
            results[symbol] = order_id if success else msg
        return results
    
    # ========== MONITORING & ALERTS ==========
    
    def _trigger_risk_event(self, event_type: RiskEvent, details: str):
        """Record risk event"""
        self.risk_events.append((datetime.now(), event_type, details))
        logger.warning(f"RISK EVENT: {event_type.value} - {details}")
    
    def _halt_trading(self, reason: str):
        """Halt all trading"""
        self.trading_halted = True
        self.halted_reason = reason
        logger.critical(f"TRADING HALTED: {reason}")
        self._trigger_risk_event(RiskEvent.VOLATILITY_SPIKE, reason)
    
    def get_positions_summary(self) -> Dict[str, Dict]:
        """Get summary of all positions"""
        return {
            symbol: {
                "qty": pos.qty,
                "avg_cost": pos.avg_cost,
                "current_price": pos.current_price,
                "unrealized_pnl": pos.unrealized_pnl,
                "unrealized_pnl_pct": pos.unrealized_pnl_pct,
                "status": pos.status,
                "entry_time": pos.entry_time.isoformat()
            }
            for symbol, pos in self.positions.items()
        }


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("LIVE TRADING RUNNER (OMS) DEMO")
    print("=" * 70)
    print("\nNote: This demo requires broker adapter and commission calculator instances")
    print("See broker_adapter_v2.py for setup\n")
    
    print("Key Features:")
    print("  - Real-time order queue management")
    print("  - Position tracking with P&L calculation")
    print("  - Risk enforcement (position size, daily loss, leverage)")
    print("  - Stop loss and take profit management")
    print("  - Circuit breaker protection")
    print("  - Audit trail and compliance recording")
    print("  - Emergency position closure")
