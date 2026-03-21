"""
BROKER ADAPTER INTERFACE - Phase 4 Module 1

Unified abstraction for multiple brokers:
- Interactive Brokers
- Alpaca Markets
- Extensible to additional brokers

This module defines the interface that all broker implementations must follow,
enabling seamless switching between brokers without changing core trading logic.

Usage:
    broker = BrokerFactory.create("alpaca", api_key="...", api_secret="...")
    broker.connect()
    
    order = broker.place_order(
        ticker="AAPL",
        qty=100,
        price=150.5,
        order_type="LIMIT",
        side="BUY"
    )
    
    positions = broker.get_positions()
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum


# ============================================================================
# ENUMS
# ============================================================================

class OrderType(str, Enum):
    """Order types."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderSide(str, Enum):
    """Buy or sell."""
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    """Order lifecycle."""
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PositionStatus(str, Enum):
    """Position states."""
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class ConnectionStatus(str, Enum):
    """Broker connection."""
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    ERROR = "ERROR"


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class Order:
    """Order representation."""
    order_id: str
    ticker: str
    qty: int
    price: float
    order_type: OrderType
    side: OrderSide
    status: OrderStatus = OrderStatus.PENDING
    filled_qty: int = 0
    avg_fill_price: float = 0.0
    commission: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    def is_filled(self) -> bool:
        """Check if order is fully filled."""
        return self.status == OrderStatus.FILLED
    
    def is_partial(self) -> bool:
        """Check if partially filled."""
        return self.status == OrderStatus.PARTIAL


@dataclass
class Position:
    """Position representation."""
    ticker: str
    qty: int
    avg_cost: float  # Average entry price
    current_price: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    status: PositionStatus = PositionStatus.OPEN
    
    @property
    def market_value(self) -> float:
        """Current value of position."""
        return self.qty * self.current_price
    
    @property
    def cost_basis(self) -> float:
        """Total cost basis."""
        return self.qty * self.avg_cost


@dataclass
class Account:
    """Account information."""
    account_id: str
    cash: float
    buying_power: float
    equity: float
    positions_value: float
    leverage: float
    margin_available: float
    multiplier: float = 1.0  # Account leverage factor


@dataclass
class Trade:
    """Executed trade."""
    trade_id: str
    ticker: str
    qty: int
    price: float
    side: OrderSide
    commission: float
    executed_at: datetime
    order_id: str = ""


# ============================================================================
# BROKER ADAPTER INTERFACE (ABSTRACT BASE)
# ============================================================================

class BrokerAdapter(ABC):
    """
    Abstract base class for all broker implementations.
    
    Each broker (Interactive Brokers, Alpaca, etc.) must implement these methods.
    """
    
    # ========== CONNECTION ==========
    
    @abstractmethod
    def connect(self) -> bool:
        """
        Connect to broker API.
        
        Returns:
            bool: True if connected, False if failed.
        
        Raises:
            ConnectionError: If connection fails
        """
        pass
    
    @abstractmethod
    def disconnect(self) -> bool:
        """
        Disconnect from broker.
        
        Returns:
            bool: True if disconnected cleanly
        """
        pass
    
    @abstractmethod
    def get_connection_status(self) -> ConnectionStatus:
        """Get current connection status."""
        pass
    
    # ========== ACCOUNT ==========
    
    @abstractmethod
    def get_account(self) -> Account:
        """
        Get account information.
        
        Returns:
            Account: Current account state (cash, equity, etc.)
        """
        pass
    
    @abstractmethod
    def get_buying_power(self) -> float:
        """
        Get available buying power.
        
        Returns:
            float: Dollars available for trading
        """
        pass
    
    # ========== POSITIONS ==========
    
    @abstractmethod
    def get_positions(self) -> List[Position]:
        """
        Get all open positions.
        
        Returns:
            List[Position]: All holdings
        """
        pass
    
    @abstractmethod
    def get_position(self, ticker: str) -> Optional[Position]:
        """
        Get specific position.
        
        Args:
            ticker: Stock symbol
        
        Returns:
            Position: Position data, or None if not held
        """
        pass
    
    # ========== ORDERS ==========
    
    @abstractmethod
    def place_order(
        self,
        ticker: str,
        qty: int,
        price: float,
        order_type: OrderType,
        side: OrderSide,
        stop_price: Optional[float] = None,
        duration: Optional[int] = None  # Seconds
    ) -> Order:
        """
        Place an order.
        
        Args:
            ticker: Stock symbol (e.g., "AAPL")
            qty: Quantity to trade
            price: Limit price (for LIMIT/STOP_LIMIT orders)
            order_type: MARKET, LIMIT, STOP, STOP_LIMIT
            side: BUY or SELL
            stop_price: Stop price (for STOP orders)
            duration: Order duration in seconds (300=5min, 3600=1hr)
        
        Returns:
            Order: Order object with ID and status
        
        Raises:
            ValueError: Invalid parameters
            RuntimeError: If order placement fails
        """
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel pending order.
        
        Args:
            order_id: Order identifier
        
        Returns:
            bool: True if cancelled, False if already filled
        """
        pass
    
    @abstractmethod
    def get_order_status(self, order_id: str) -> OrderStatus:
        """
        Get order status.
        
        Args:
            order_id: Order identifier
        
        Returns:
            OrderStatus: Current status
        """
        pass
    
    @abstractmethod
    def get_orders(self, status: Optional[OrderStatus] = None) -> List[Order]:
        """
        Get all orders (optionally filtered by status).
        
        Args:
            status: Filter to specific status, or None for all
        
        Returns:
            List[Order]: Matching orders
        """
        pass
    
    # ========== FILLS & TRADES ==========
    
    @abstractmethod
    def get_trades(self) -> List[Trade]:
        """
        Get completed trades.
        
        Returns:
            List[Trade]: Historical trades
        """
        pass
    
    @abstractmethod
    def get_fills(self, order_id: str) -> List[Dict[str, Any]]:
        """
        Get partial fills for an order.
        
        Args:
            order_id: Order identifier
        
        Returns:
            List[Dict]: Fill details (qty, price, timestamp)
        """
        pass
    
    # ========== MARKET DATA ==========
    
    @abstractmethod
    def get_last_price(self, ticker: str) -> float:
        """
        Get last traded price.
        
        Args:
            ticker: Stock symbol
        
        Returns:
            float: Last price
        """
        pass
    
    @abstractmethod
    def get_bid_ask(self, ticker: str) -> tuple:
        """
        Get current bid/ask.
        
        Args:
            ticker: Stock symbol
        
        Returns:
            tuple: (bid_price, ask_price)
        """
        pass
    
    # ========== ERROR HANDLING ==========
    
    @abstractmethod
    def get_last_error(self) -> Optional[str]:
        """Get last error message."""
        pass
    
    @abstractmethod
    def clear_error(self):
        """Clear error state."""
        pass


# ============================================================================
# INTERACTIVE BROKERS ADAPTER (IMPLEMENTATION)
# ============================================================================

class InteractiveBrokersAdapter(BrokerAdapter):
    """
    Adapter for Interactive Brokers TWS API.
    
    Requires: ib-insync library and running TWS/Gateway instance
    
    Example:
        adapter = InteractiveBrokersAdapter(
            host="127.0.0.1",
            port=7497,
            client_id=1
        )
        adapter.connect()
    """
    
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7497,
        client_id: int = 1
    ):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.connection_status = ConnectionStatus.DISCONNECTED
        self.last_error = None
        
        # Would import here: from ib_insync import IB, Stock, Order
        self.ib = None
    
    def connect(self) -> bool:
        """Connect to TWS/Gateway."""
        try:
            from ib_insync import IB
            self.ib = IB()
            self.ib.connect(self.host, self.port, clientId=self.client_id)
            self.connection_status = ConnectionStatus.CONNECTED
            return True
        except Exception as e:
            self.last_error = str(e)
            self.connection_status = ConnectionStatus.ERROR
            return False
    
    def disconnect(self) -> bool:
        """Disconnect from TWS/Gateway."""
        try:
            if self.ib:
                self.ib.disconnect()
            self.connection_status = ConnectionStatus.DISCONNECTED
            return True
        except Exception as e:
            self.last_error = str(e)
            return False
    
    def get_connection_status(self) -> ConnectionStatus:
        """Get connection status."""
        return self.connection_status
    
    def get_account(self) -> Account:
        """Get account information from IB."""
        # Implementation would query IB API
        raise NotImplementedError("See full implementation in broker_adapter.py")
    
    def get_buying_power(self) -> float:
        """Get available buying power."""
        account = self.get_account()
        return account.buying_power
    
    def get_positions(self) -> List[Position]:
        """Get positions from IB."""
        raise NotImplementedError()
    
    def get_position(self, ticker: str) -> Optional[Position]:
        """Get specific position."""
        raise NotImplementedError()
    
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
        """Place order on Interactive Brokers."""
        raise NotImplementedError()
    
    # ... other methods ...


# ============================================================================
# ALPACA ADAPTER (IMPLEMENTATION)
# ============================================================================

class AlpacaAdapter(BrokerAdapter):
    """
    Adapter for Alpaca Markets API.
    
    Requires: alpaca-trade-api library
    
    Example:
        adapter = AlpacaAdapter(
            api_key="your-api-key",
            api_secret="your-secret",
            base_url="https://paper-api.alpaca.markets"  # Paper trading
        )
        adapter.connect()
    """
    
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = "https://paper-api.alpaca.markets"
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self.connection_status = ConnectionStatus.DISCONNECTED
        self.last_error = None
        self.api = None
    
    def connect(self) -> bool:
        """Connect to Alpaca API."""
        try:
            from alpaca_trade_api import REST
            self.api = REST(
                self.api_key,
                self.api_secret,
                self.base_url
            )
            # Verify connection
            account = self.api.get_account()
            self.connection_status = ConnectionStatus.CONNECTED
            return True
        except Exception as e:
            self.last_error = str(e)
            self.connection_status = ConnectionStatus.ERROR
            return False
    
    def disconnect(self) -> bool:
        """Disconnect from Alpaca."""
        self.connection_status = ConnectionStatus.DISCONNECTED
        return True
    
    def get_connection_status(self) -> ConnectionStatus:
        """Get connection status."""
        return self.connection_status
    
    def get_account(self) -> Account:
        """Get account from Alpaca."""
        raise NotImplementedError()
    
    # ... other methods ...


# ============================================================================
# BROKER FACTORY
# ============================================================================

class BrokerFactory:
    """Factory for creating broker adapters."""
    
    _adapters = {
        "interactive_brokers": InteractiveBrokersAdapter,
        "alpaca": AlpacaAdapter,
    }
    
    @classmethod
    def create(cls, broker_name: str, **kwargs) -> BrokerAdapter:
        """
        Create broker adapter.
        
        Args:
            broker_name: "interactive_brokers" or "alpaca"
            **kwargs: Arguments for adapter constructor
        
        Returns:
            BrokerAdapter: Configured broker instance
        
        Example:
            broker = BrokerFactory.create(
                "alpaca",
                api_key="PK123456",
                api_secret="secret",
                base_url="https://paper-api.alpaca.markets"
            )
        """
        if broker_name not in cls._adapters:
            raise ValueError(f"Unknown broker: {broker_name}")
        
        adapter_class = cls._adapters[broker_name]
        return adapter_class(**kwargs)
    
    @classmethod
    def register_adapter(cls, name: str, adapter_class: type):
        """Register custom broker adapter."""
        cls._adapters[name] = adapter_class


# ============================================================================
# USAGE EXAMPLE
# ============================================================================

if __name__ == "__main__":
    print("Broker Adapter Interface")
    print("=" * 60)
    
    print("\nIntegration Brokers:")
    print("  BrokerFactory.create('interactive_brokers', host='127.0.0.1')")
    
    print("\nAlpaca Markets:")
    print("  BrokerFactory.create('alpaca', api_key='...', api_secret='...')")
    
    print("\nUsage Pattern:")
    print("""
    broker = BrokerFactory.create('alpaca', api_key='...', api_secret='...')
    broker.connect()
    
    # Place order
    order = broker.place_order(
        ticker='AAPL',
        qty=100,
        price=150.5,
        order_type=OrderType.LIMIT,
        side=OrderSide.BUY
    )
    
    # Track execution
    while not order.is_filled():
        status = broker.get_order_status(order.order_id)
        print(f"Status: {status}")
    
    broker.disconnect()
    """)
