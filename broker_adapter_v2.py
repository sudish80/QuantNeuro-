"""
PHASE 4 MODULE 1 (REVISED): Broker Adapter Interface
======================================================

Unified multi-broker abstraction layer supporting Interactive Brokers, Alpaca, and Binance.
Handles market/limit/stop orders, real-time positions, commission/slippage calculations.

Author: QuantNeuro Trading System
Version: 4.0
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from enum import Enum
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS & DATA CLASSES
# ============================================================================

class OrderType(Enum):
    """Order types"""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderSide(Enum):
    """Order side (BUY/SELL)"""
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    """Order lifecycle status"""
    PENDING = "pending"  # Created locally, not sent
    SUBMITTED = "submitted"  # Sent to broker, awaiting confirmation
    ACCEPTED = "accepted"  # Broker confirmed
    PARTIAL = "partial"  # Partially filled
    FILLED = "filled"  # Completely filled
    CANCELLED = "cancelled"  # Cancelled by user/system
    REJECTED = "rejected"  # Rejected by broker
    EXPIRED = "expired"  # Order expired


class PositionStatus(Enum):
    """Position status"""
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


class ConnectionStatus(Enum):
    """Broker connection status"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class Order:
    """Order record with full lifecycle tracking"""
    order_id: str
    symbol: str
    qty: int
    price: float
    order_type: OrderType
    side: OrderSide
    status: OrderStatus = OrderStatus.PENDING
    filled_qty: int = 0
    avg_fill_price: float = 0.0
    commission: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
    submitted_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    stop_price: Optional[float] = None  # For STOP/STOP_LIMIT orders


@dataclass
class Position:
    """Position tracking with P&L"""
    symbol: str
    qty: int
    avg_cost: float
    current_price: float
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    status: PositionStatus = PositionStatus.OPEN


@dataclass
class Account:
    """Account information"""
    account_id: str
    cash: float
    buying_power: float
    equity: float
    positions_value: float
    leverage: float = 1.0
    margin_available: float = 0.0
    multiplier: float = 1.0  # For futures


@dataclass
class Trade:
    """Executed trade record"""
    trade_id: str
    order_id: str
    symbol: str
    qty: int
    price: float
    side: OrderSide
    commission: float
    executed_at: datetime


# ============================================================================
# ABSTRACT BROKER ADAPTER
# ============================================================================

class BrokerAdapter(ABC):
    """
    Abstract base class for broker integration.
    
    Unified interface for:
    - Interactive Brokers (IB)
    - Alpaca Markets (REST API)
    - Binance (Crypto, REST/WebSocket)
    """
    
    def __init__(self, broker_name: str):
        self.broker_name = broker_name
        self.connection_status = ConnectionStatus.DISCONNECTED
        self.last_error: Optional[str] = None
    
    # ========== CONNECTION ==========
    @abstractmethod
    async def connect(self):
        """Establish broker connection"""
        pass
    
    @abstractmethod
    async def disconnect(self):
        """Close broker connection"""
        pass
    
    @abstractmethod
    def get_connection_status(self) -> ConnectionStatus:
        """Get current connection status"""
        pass
    
    # ========== ACCOUNT ==========
    @abstractmethod
    def get_account(self) -> Account:
        """Get account information (cash, equity, positions)"""
        pass
    
    @abstractmethod
    def get_buying_power(self) -> float:
        """Get available buying power"""
        pass
    
    # ========== POSITIONS ==========
    @abstractmethod
    def get_positions(self) -> List[Position]:
        """Get all open positions"""
        pass
    
    @abstractmethod
    def get_position(self, symbol: str) -> Optional[Position]:
        """Get single position"""
        pass
    
    # ========== ORDERS ==========
    @abstractmethod
    def place_order(self, symbol: str, qty: int, price: float,
                   order_type: OrderType, side: OrderSide,
                   stop_price: Optional[float] = None) -> Order:
        """
        Place order
        
        Args:
            symbol: Stock/crypto ticker
            qty: Quantity
            price: Limit price (ignored for MARKET)
            order_type: MARKET, LIMIT, STOP, STOP_LIMIT
            side: BUY or SELL
            stop_price: For STOP/STOP_LIMIT orders
        
        Returns:
            Order object
        """
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel pending order"""
        pass
    
    @abstractmethod
    def get_order_status(self, order_id: str) -> OrderStatus:
        """Get order status"""
        pass
    
    @abstractmethod
    def get_orders(self, status: Optional[OrderStatus] = None) -> List[Order]:
        """Get orders (optionally filtered by status)"""
        pass
    
    # ========== FILLS & TRADES ==========
    @abstractmethod
    def get_trades(self) -> List[Trade]:
        """Get all executed trades"""
        pass
    
    @abstractmethod
    def get_fills(self, order_id: str) -> List[Dict]:
        """Get fills for specific order"""
        pass
    
    # ========== MARKET DATA ==========
    @abstractmethod
    def get_last_price(self, symbol: str) -> float:
        """Get last trade price"""
        pass
    
    @abstractmethod
    def get_bid_ask(self, symbol: str) -> Tuple[float, float]:
        """Get bid/ask prices"""
        pass
    
    # ========== ERROR HANDLING ==========
    @abstractmethod
    def get_last_error(self) -> Optional[str]:
        """Get last error message"""
        pass
    
    @abstractmethod
    def clear_error(self):
        """Clear error state"""
        pass


# ============================================================================
# INTERACTIVE BROKERS ADAPTER
# ============================================================================

class InteractiveBrokersAdapter(BrokerAdapter):
    """Interactive Brokers (TWS/Gateway) integration"""
    
    def __init__(self, host: str = "127.0.0.1", port: int = 7497, client_id: int = 1):
        super().__init__("InteractiveBrokers")
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib_connection = None
        self.orders: Dict[str, Order] = {}
        self.positions: Dict[str, Position] = {}
    
    async def connect(self):
        """Connect to IB TWS/Gateway"""
        try:
            # Placeholder: Real implementation would use ib_insync
            # from ib_insync import IB
            # self.ib_connection = IB()
            # await self.ib_connection.connectAsync(self.host, self.port, self.client_id)
            self.connection_status = ConnectionStatus.CONNECTED
            logger.info(f"Connected to IB {self.host}:{self.port}")
        except Exception as e:
            self.connection_status = ConnectionStatus.ERROR
            self.last_error = str(e)
            logger.error(f"IB connection failed: {e}")
    
    async def disconnect(self):
        """Disconnect from IB"""
        if self.ib_connection:
            # await self.ib_connection.disconnectAsync()
            pass
        self.connection_status = ConnectionStatus.DISCONNECTED
    
    def get_connection_status(self) -> ConnectionStatus:
        return self.connection_status
    
    def get_account(self) -> Account:
        """Get account from IB"""
        # Real implementation: self.ib_connection.accountValues()
        return Account(
            account_id="IB_ACCOUNT",
            cash=100000.0,
            buying_power=300000.0,
            equity=500000.0,
            positions_value=400000.0,
            leverage=3.0
        )
    
    def get_buying_power(self) -> float:
        return self.get_account().buying_power
    
    def get_positions(self) -> List[Position]:
        return list(self.positions.values())
    
    def get_position(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)
    
    def place_order(self, symbol: str, qty: int, price: float,
                   order_type: OrderType, side: OrderSide,
                   stop_price: Optional[float] = None) -> Order:
        """Place order on IB"""
        order_id = f"IB_{len(self.orders)}"
        order = Order(
            order_id=order_id,
            symbol=symbol,
            qty=qty,
            price=price,
            order_type=order_type,
            side=side,
            stop_price=stop_price
        )
        self.orders[order_id] = order
        logger.info(f"Order placed: {order_id} {side.value} {qty} {symbol} @ {price}")
        return order
    
    def cancel_order(self, order_id: str) -> bool:
        if order_id in self.orders:
            self.orders[order_id].status = OrderStatus.CANCELLED
            logger.info(f"Order cancelled: {order_id}")
            return True
        return False
    
    def get_order_status(self, order_id: str) -> OrderStatus:
        return self.orders.get(order_id, Order(
            "UNKNOWN", "", 0, 0, OrderType.MARKET, OrderSide.BUY
        )).status
    
    def get_orders(self, status: Optional[OrderStatus] = None) -> List[Order]:
        if status:
            return [o for o in self.orders.values() if o.status == status]
        return list(self.orders.values())
    
    def get_trades(self) -> List[Trade]:
        filled_orders = [o for o in self.orders.values() if o.status == OrderStatus.FILLED]
        return [
            Trade(
                trade_id=f"TRADE_{o.order_id}",
                order_id=o.order_id,
                symbol=o.symbol,
                qty=o.filled_qty,
                price=o.avg_fill_price,
                side=o.side,
                commission=o.commission,
                executed_at=o.filled_at or datetime.now()
            )
            for o in filled_orders
        ]
    
    def get_fills(self, order_id: str) -> List[Dict]:
        order = self.orders.get(order_id)
        if not order or order.filled_qty == 0:
            return []
        return [{
            "qty": order.filled_qty,
            "price": order.avg_fill_price,
            "commission": order.commission,
            "timestamp": order.filled_at
        }]
    
    def get_last_price(self, symbol: str) -> float:
        # Real: self.ib_connection.reqMktData(...)
        return 100.0  # Placeholder
    
    def get_bid_ask(self, symbol: str) -> Tuple[float, float]:
        # Real: self.ib_connection.reqMktData(...)
        return (99.95, 100.05)  # Placeholder
    
    def get_last_error(self) -> Optional[str]:
        return self.last_error
    
    def clear_error(self):
        self.last_error = None


# ============================================================================
# ALPACA ADAPTER
# ============================================================================

class AlpacaAdapter(BrokerAdapter):
    """Alpaca Markets (REST API) integration"""
    
    def __init__(self, api_key: str, api_secret: str, 
                 base_url: str = "https://paper-api.alpaca.markets"):
        super().__init__("Alpaca")
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self.session = None
        self.orders: Dict[str, Order] = {}
    
    async def connect(self):
        """Connect to Alpaca API"""
        try:
            # Real: import aiohttp; create session
            # self.session = aiohttp.ClientSession(...)
            self.connection_status = ConnectionStatus.CONNECTED
            logger.info("Connected to Alpaca API")
        except Exception as e:
            self.connection_status = ConnectionStatus.ERROR
            self.last_error = str(e)
    
    async def disconnect(self):
        """Disconnect from Alpaca"""
        if self.session:
            # await self.session.close()
            pass
        self.connection_status = ConnectionStatus.DISCONNECTED
    
    def get_connection_status(self) -> ConnectionStatus:
        return self.connection_status
    
    def get_account(self) -> Account:
        # Real: GET /v2/account
        return Account(
            account_id="ALPACA_ACCOUNT",
            cash=50000.0,
            buying_power=50000.0,
            equity=500000.0,
            positions_value=450000.0,
            leverage=1.0
        )
    
    def get_buying_power(self) -> float:
        return self.get_account().buying_power
    
    def get_positions(self) -> List[Position]:
        # Real: GET /v2/positions
        return []
    
    def get_position(self, symbol: str) -> Optional[Position]:
        for pos in self.get_positions():
            if pos.symbol == symbol:
                return pos
        return None
    
    def place_order(self, symbol: str, qty: int, price: float,
                   order_type: OrderType, side: OrderSide,
                   stop_price: Optional[float] = None) -> Order:
        """Place order via Alpaca API"""
        order_id = f"ALPACA_{len(self.orders)}"
        order = Order(
            order_id=order_id,
            symbol=symbol,
            qty=qty,
            price=price,
            order_type=order_type,
            side=side,
            stop_price=stop_price,
            status=OrderStatus.SUBMITTED
        )
        self.orders[order_id] = order
        logger.info(f"Alpaca order: {order_id}")
        return order
    
    def cancel_order(self, order_id: str) -> bool:
        if order_id in self.orders:
            self.orders[order_id].status = OrderStatus.CANCELLED
            return True
        return False
    
    def get_order_status(self, order_id: str) -> OrderStatus:
        return self.orders.get(order_id, Order(
            "UNKNOWN", "", 0, 0, OrderType.MARKET, OrderSide.BUY
        )).status
    
    def get_orders(self, status: Optional[OrderStatus] = None) -> List[Order]:
        if status:
            return [o for o in self.orders.values() if o.status == status]
        return list(self.orders.values())
    
    def get_trades(self) -> List[Trade]:
        filled_orders = [o for o in self.orders.values() if o.status == OrderStatus.FILLED]
        return [
            Trade(
                trade_id=f"TRADE_{o.order_id}",
                order_id=o.order_id,
                symbol=o.symbol,
                qty=o.filled_qty,
                price=o.avg_fill_price,
                side=o.side,
                commission=o.commission,
                executed_at=o.filled_at or datetime.now()
            )
            for o in filled_orders
        ]
    
    def get_fills(self, order_id: str) -> List[Dict]:
        order = self.orders.get(order_id)
        if not order or order.filled_qty == 0:
            return []
        return [{
            "qty": order.filled_qty,
            "price": order.avg_fill_price,
            "commission": order.commission
        }]
    
    def get_last_price(self, symbol: str) -> float:
        return 100.0  # Placeholder
    
    def get_bid_ask(self, symbol: str) -> Tuple[float, float]:
        return (99.95, 100.05)
    
    def get_last_error(self) -> Optional[str]:
        return self.last_error
    
    def clear_error(self):
        self.last_error = None


# ============================================================================
# BINANCE ADAPTER
# ============================================================================

class BinanceAdapter(BrokerAdapter):
    """Binance Futures/Spot trading integration"""
    
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        super().__init__("Binance")
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.base_url = "https://testnet.binancefuture.com" if testnet else "https://fapi.binance.com"
        self.session = None
        self.orders: Dict[str, Order] = {}
        self.positions: Dict[str, Position] = {}
    
    async def connect(self):
        """Connect to Binance API"""
        try:
            # Real: import aiohttp; setup session with auth headers
            # self.session = aiohttp.ClientSession(
            #     headers={
            #         "X-MBX-APIKEY": self.api_key
            #     }
            # )
            self.connection_status = ConnectionStatus.CONNECTED
            logger.info(f"Connected to Binance {'Testnet' if self.testnet else 'Live'}")
        except Exception as e:
            self.connection_status = ConnectionStatus.ERROR
            self.last_error = str(e)
            logger.error(f"Binance connection failed: {e}")
    
    async def disconnect(self):
        """Disconnect from Binance"""
        if self.session:
            # await self.session.close()
            pass
        self.connection_status = ConnectionStatus.DISCONNECTED
    
    def get_connection_status(self) -> ConnectionStatus:
        return self.connection_status
    
    def get_account(self) -> Account:
        """Get account from Binance Futures"""
        # Real: GET /fapi/v3/account
        return Account(
            account_id="BINANCE_FUTURES",
            cash=10000.0,
            buying_power=10000.0,
            equity=10000.0,
            positions_value=0.0,
            leverage=10.0,
            multiplier=1.0
        )
    
    def get_buying_power(self) -> float:
        return self.get_account().buying_power
    
    def get_positions(self) -> List[Position]:
        """Get open Futures positions"""
        # Real: GET /fapi/v3/openOrders + /fapi/v3/positionRisk
        return list(self.positions.values())
    
    def get_position(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)
    
    def place_order(self, symbol: str, qty: int, price: float,
                   order_type: OrderType, side: OrderSide,
                   stop_price: Optional[float] = None) -> Order:
        """Place order on Binance Futures"""
        order_id = f"BNB_{len(self.orders)}"
        order = Order(
            order_id=order_id,
            symbol=symbol,
            qty=qty,
            price=price,
            order_type=order_type,
            side=side,
            stop_price=stop_price,
            status=OrderStatus.SUBMITTED
        )
        self.orders[order_id] = order
        logger.info(f"Binance order: {order_id} {side.value} {qty} {symbol}")
        return order
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel order on Binance"""
        if order_id in self.orders:
            self.orders[order_id].status = OrderStatus.CANCELLED
            logger.info(f"Binance order cancelled: {order_id}")
            return True
        return False
    
    def get_order_status(self, order_id: str) -> OrderStatus:
        return self.orders.get(order_id, Order(
            "UNKNOWN", "", 0, 0, OrderType.MARKET, OrderSide.BUY
        )).status
    
    def get_orders(self, status: Optional[OrderStatus] = None) -> List[Order]:
        if status:
            return [o for o in self.orders.values() if o.status == status]
        return list(self.orders.values())
    
    def get_trades(self) -> List[Trade]:
        """Get executed trades from Binance"""
        filled_orders = [o for o in self.orders.values() if o.status == OrderStatus.FILLED]
        return [
            Trade(
                trade_id=f"TRADE_{o.order_id}",
                order_id=o.order_id,
                symbol=o.symbol,
                qty=o.filled_qty,
                price=o.avg_fill_price,
                side=o.side,
                commission=o.commission,
                executed_at=o.filled_at or datetime.now()
            )
            for o in filled_orders
        ]
    
    def get_fills(self, order_id: str) -> List[Dict]:
        """Get fills for order"""
        order = self.orders.get(order_id)
        if not order or order.filled_qty == 0:
            return []
        return [{
            "qty": order.filled_qty,
            "price": order.avg_fill_price,
            "commission": order.commission,
            "timestamp": order.filled_at
        }]
    
    def get_last_price(self, symbol: str) -> float:
        # Real: GET /fapi/v1/ticker/price?symbol={symbol}
        return 50000.0  # Placeholder (BTC/USDT)
    
    def get_bid_ask(self, symbol: str) -> Tuple[float, float]:
        # Real: GET /fapi/v1/ticker/bookTicker?symbol={symbol}
        return (49950.0, 50050.0)  # Placeholder
    
    def get_last_error(self) -> Optional[str]:
        return self.last_error
    
    def clear_error(self):
        self.last_error = None


# ============================================================================
# COMMISSION & SLIPPAGE UTILITIES
# ============================================================================

class CommissionCalculator:
    """Calculate commissions and slippage for different brokers"""
    
    # Broker commission rates (bps = basis points, 1 bps = 0.01%)
    COMMISSIONS = {
        "interactive_brokers": 0.5,  # 0.5 bps per share
        "alpaca": 0.0,  # Free trading
        "binance": 4.0,  # 0.04% = 4 bps
    }
    
    # Average slippage (bps)
    SLIPPAGE = {
        "interactive_brokers": 1.0,
        "alpaca": 2.0,
        "binance": 1.5,
    }
    
    @staticmethod
    def calculate_commission(broker: str, trade_value: float, qty: int) -> float:
        """
        Calculate commission for trade
        
        Args:
            broker: Broker name
            trade_value: Total trade value (qty * price)
            qty: Quantity (for IB per-share calculation)
        
        Returns:
            Commission in currency units
        """
        commission_rate = CommissionCalculator.COMMISSIONS.get(broker, 0.5)
        
        if broker == "interactive_brokers":
            # IB: $0.005 per share, min $1, max 0.1% of trade
            per_share = max(1.0, qty * 0.005)
            percentage = trade_value * 0.001
            return min(per_share, percentage)
        else:
            # Binance, Alpaca: percentage-based
            return (trade_value * commission_rate) / 10000  # Convert bps to decimal
    
    @staticmethod
    def calculate_slippage(broker: str, trade_value: float, qty: int) -> float:
        """
        Estimate slippage for trade
        
        Args:
            broker: Broker name
            trade_value: Total trade value
            qty: Quantity
        
        Returns:
            Slippage in currency units
        """
        slippage_bps = CommissionCalculator.SLIPPAGE.get(broker, 2.0)
        return (trade_value * slippage_bps) / 10000  # Convert bps to decimal
    
    @staticmethod
    def calculate_total_cost(broker: str, trade_value: float, qty: int) -> float:
        """
        Calculate total trading cost (commission + slippage)
        
        Returns:
            Total cost in currency units
        """
        commission = CommissionCalculator.calculate_commission(broker, trade_value, qty)
        slippage = CommissionCalculator.calculate_slippage(broker, trade_value, qty)
        return commission + slippage


# ============================================================================
# BROKER FACTORY
# ============================================================================

class BrokerFactory:
    """Factory for creating broker adapters"""
    
    _adapters: Dict[str, type] = {
        "interactive_brokers": InteractiveBrokersAdapter,
        "alpaca": AlpacaAdapter,
        "binance": BinanceAdapter,
    }
    
    @classmethod
    def create(cls, broker_name: str, **kwargs) -> BrokerAdapter:
        """
        Create broker adapter instance
        
        Args:
            broker_name: "interactive_brokers", "alpaca", "binance"
            **kwargs: Broker-specific arguments
                - IB: host, port, client_id
                - Alpaca: api_key, api_secret, base_url
                - Binance: api_key, api_secret, testnet
        
        Returns:
            BrokerAdapter subclass instance
        """
        adapter_class = cls._adapters.get(broker_name.lower())
        if not adapter_class:
            raise ValueError(f"Unknown broker: {broker_name}")
        return adapter_class(**kwargs)
    
    @classmethod
    def register_adapter(cls, name: str, adapter_class: type):
        """Register custom broker adapter"""
        cls._adapters[name.lower()] = adapter_class
    
    @classmethod
    def list_brokers(cls) -> List[str]:
        """List available brokers"""
        return list(cls._adapters.keys())


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    import asyncio
    
    async def example_usage():
        # Create adapters for all brokers
        ib = BrokerFactory.create(
            "interactive_brokers",
            host="127.0.0.1",
            port=7497,
            client_id=1
        )
        
        alpaca = BrokerFactory.create(
            "alpaca",
            api_key="YOUR_KEY",
            api_secret="YOUR_SECRET"
        )
        
        binance = BrokerFactory.create(
            "binance",
            api_key="YOUR_KEY",
            api_secret="YOUR_SECRET",
            testnet=True
        )
        
        # Print initial status
        print("=" * 60)
        print("BROKER ADAPTER DEMO")
        print("=" * 60)
        print(f"Available brokers: {BrokerFactory.list_brokers()}")
        print()
        
        # Test each broker
        for adapter in [ib, alpaca, binance]:
            print(f"[{adapter.broker_name}] Status: {adapter.get_connection_status().value}")
            account = adapter.get_account()
            print(f"  Account: {account.account_id}")
            print(f"  Cash: ${account.cash:,.2f}")
            print(f"  Buying Power: ${account.buying_power:,.2f}")
            print(f"  Leverage: {account.leverage}x")
            print()
        
        # Commission & slippage examples
        print("=" * 60)
        print("COMMISSION & SLIPPAGE CALCULATIONS")
        print("=" * 60)
        
        test_cases = [
            ("Stock", 100.0, 100, "interactive_brokers"),
            ("Stock", 100.0, 100, "alpaca"),
            ("Crypto", 50000.0, 0.01, "binance"),
        ]
        
        for asset, price, qty, broker in test_cases:
            trade_value = price * qty
            commission = CommissionCalculator.calculate_commission(broker, trade_value, qty)
            slippage = CommissionCalculator.calculate_slippage(broker, trade_value, qty)
            total_cost = CommissionCalculator.calculate_total_cost(broker, trade_value, qty)
            
            print(f"[{broker.upper()}] {asset}")
            print(f"  Price: ${price:,.2f}, Qty: {qty}")
            print(f"  Trade Value: ${trade_value:,.2f}")
            print(f"  Commission: ${commission:,.4f}")
            print(f"  Slippage: ${slippage:,.4f}")
            print(f"  Total Cost: ${total_cost:,.4f}")
            print(f"  Cost % of trade: {(total_cost / trade_value) * 100:.4f}%")
            print()
    
    asyncio.run(example_usage())
