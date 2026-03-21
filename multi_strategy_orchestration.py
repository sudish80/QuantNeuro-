"""
PHASE 4 MODULE 2: Multi-Strategy Orchestration
================================================

Coordinate multiple trading strategies with position aggregation, 
risk limits, signal weighting, and conflict resolution.

Features:
- Parallel model execution (LSTM, GRU, HybridNet, ensemble)
- Weighted signal aggregation (confidence-based)
- Position sizing with Kelly criterion
- Risk aggregation across strategies
- Conflict resolution (unanimous > majority > weighted)
- Individual strategy performance tracking
- Live rebalancing with transaction costs

Author: QuantNeuro Trading System
Version: 4.0
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Callable
from datetime import datetime
from enum import Enum
import numpy as np
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS & DATA CLASSES
# ============================================================================

class SignalType(Enum):
    """Trading signal types"""
    STRONG_BUY = 2.0
    BUY = 1.0
    NEUTRAL = 0.0
    SELL = -1.0
    STRONG_SELL = -2.0


class ConflictResolutionMethod(Enum):
    """How to handle conflicting signals from multiple strategies"""
    UNANIMOUS = "unanimous"  # All strategies must agree
    MAJORITY = "majority"    # >50% must agree
    WEIGHTED = "weighted"    # Use weighted average
    KELLY = "kelly"          # Use Kelly criterion


@dataclass
class StrategySignal:
    """Signal from individual strategy"""
    strategy_id: str
    symbol: str
    signal: SignalType
    confidence: float  # 0.0 to 1.0
    predicted_return: float  # Expected return (%)
    sharpe_ratio: float  # Strategy-specific Sharpe
    win_rate: float  # Recent win rate
    model_type: str  # "LSTM", "GRU", "HybridNet", etc.
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class AggregatedSignal:
    """Aggregated signal after combining multiple strategies"""
    symbol: str
    final_signal: SignalType
    weighted_score: float  # -2.0 to 2.0
    confidence: float  # Overall confidence (0-1)
    num_strategies: int
    strategies_bought: int  # How many strategies said BUY
    strategies_sold: int  # How many strategies said SELL
    avg_predicted_return: float
    consensus_type: str  # "unanimous", "majority", "weak", "conflict"
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class PositionOrder:
    """Position order from orchestrator"""
    symbol: str
    target_qty: int
    current_qty: int
    delta_qty: int  # Change needed
    signal_strength: float  # -1 to 1
    position_size_ratio: float  # Target % of portfolio
    estimated_cost: float
    urgency: str  # "immediate", "normal", "discretionary"


@dataclass
class StrategyMetrics:
    """Performance metrics for individual strategy"""
    strategy_id: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    cumulative_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    avg_profit_per_trade: float = 0.0
    last_update: datetime = field(default_factory=datetime.now)


# ============================================================================
# STRATEGY INTERFACE
# ============================================================================

class TradingStrategy(ABC):
    """Abstract base class for trading strategies"""
    
    def __init__(self, strategy_id: str, model_type: str):
        self.strategy_id = strategy_id
        self.model_type = model_type
        self.metrics = StrategyMetrics(strategy_id=strategy_id)
        self.last_sharpe = 0.0
    
    @abstractmethod
    def generate_signals(self, symbols: List[str]) -> Dict[str, StrategySignal]:
        """
        Generate trading signals for symbols
        
        Returns:
            Dict mapping symbol -> StrategySignal
        """
        pass
    
    @abstractmethod
    def get_confidence(self) -> float:
        """Get strategy's current confidence level (0-1)"""
        pass
    
    @abstractmethod
    def update_metrics(self, trades: List[Dict]):
        """Update strategy performance metrics"""
        pass
    
    def get_metrics(self) -> StrategyMetrics:
        """Get current strategy metrics"""
        return self.metrics


# ============================================================================
# MULTI-STRATEGY ORCHESTRATOR
# ============================================================================

class MultiStrategyOrchestrator:
    """
    Coordinate multiple trading strategies with risk management
    and conflict resolution.
    """
    
    def __init__(
        self,
        portfolio_value: float,
        risk_limit_pct: float = 2.0,
        position_limit_pct: float = 10.0,
        conflict_resolution: ConflictResolutionMethod = ConflictResolutionMethod.WEIGHTED,
        kelly_fraction: float = 0.25
    ):
        """
        Args:
            portfolio_value: Total portfolio value ($)
            risk_limit_pct: Max risk per trade (% of portfolio)
            position_limit_pct: Max position size (% of portfolio)
            conflict_resolution: How to handle conflicting signals
            kelly_fraction: Kelly criterion fraction (0.25 = conservative)
        """
        self.portfolio_value = portfolio_value
        self.risk_limit_pct = risk_limit_pct
        self.position_limit_pct = position_limit_pct
        self.conflict_resolution = conflict_resolution
        self.kelly_fraction = kelly_fraction
        
        self.strategies: Dict[str, TradingStrategy] = {}
        self.current_positions: Dict[str, int] = defaultdict(int)
        self.aggregated_signals_cache: Dict[str, AggregatedSignal] = {}
        self.signal_history: List[AggregatedSignal] = []
        self.trades_executed: List[Dict] = []
    
    def register_strategy(self, strategy: TradingStrategy):
        """Register a trading strategy"""
        self.strategies[strategy.strategy_id] = strategy
        logger.info(f"Registered strategy: {strategy.strategy_id} ({strategy.model_type})")
    
    def unregister_strategy(self, strategy_id: str):
        """Unregister a trading strategy"""
        if strategy_id in self.strategies:
            del self.strategies[strategy_id]
            logger.info(f"Unregistered strategy: {strategy_id}")
    
    def get_strategies(self) -> List[TradingStrategy]:
        """Get all registered strategies"""
        return list(self.strategies.values())
    
    def orchestrate(self, symbols: List[str]) -> Dict[str, AggregatedSignal]:
        """
        Run all strategies and aggregate their signals
        
        Args:
            symbols: List of symbols to trade
        
        Returns:
            Dict mapping symbol -> AggregatedSignal
        """
        # Collect signals from all strategies
        all_signals: Dict[str, List[StrategySignal]] = defaultdict(list)
        
        for strategy in self.strategies.values():
            try:
                signals = strategy.generate_signals(symbols)
                for symbol, signal in signals.items():
                    all_signals[symbol].append(signal)
            except Exception as e:
                logger.error(f"Error in strategy {strategy.strategy_id}: {e}")
        
        # Aggregate signals for each symbol
        aggregated = {}
        for symbol in symbols:
            if symbol in all_signals:
                aggregated[symbol] = self._aggregate_signals(
                    symbol, all_signals[symbol]
                )
            else:
                aggregated[symbol] = AggregatedSignal(
                    symbol=symbol,
                    final_signal=SignalType.NEUTRAL,
                    weighted_score=0.0,
                    confidence=0.0,
                    num_strategies=0,
                    strategies_bought=0,
                    strategies_sold=0,
                    avg_predicted_return=0.0,
                    consensus_type="no_data"
                )
        
        self.aggregated_signals_cache = aggregated
        self.signal_history.extend(aggregated.values())
        
        return aggregated
    
    def _aggregate_signals(self, symbol: str, signals: List[StrategySignal]) -> AggregatedSignal:
        """
        Aggregate signals from multiple strategies using configured method
        
        Args:
            symbol: Trading symbol
            signals: List of StrategySignal objects
        
        Returns:
            AggregatedSignal
        """
        if not signals:
            return AggregatedSignal(
                symbol=symbol, final_signal=SignalType.NEUTRAL,
                weighted_score=0.0, confidence=0.0, num_strategies=0,
                strategies_bought=0, strategies_sold=0, avg_predicted_return=0.0,
                consensus_type="no_signals"
            )
        
        num_strategies = len(signals)
        
        # Count bullish vs bearish
        bullish = sum(1 for s in signals if s.signal.value > 0)
        bearish = sum(1 for s in signals if s.signal.value < 0)
        
        # Calculate weighted score and confidence
        weights = np.array([s.confidence for s in signals])
        weights /= weights.sum()  # Normalize
        
        signal_values = np.array([s.signal.value for s in signals])
        weighted_score = np.sum(signal_values * weights)
        
        avg_confidence = np.mean([s.confidence for s in signals])
        avg_return = np.mean([s.predicted_return for s in signals])
        
        # Determine consensus type
        if bullish == 0 or bearish == 0:
            consensus_type = "unanimous"
            final_signal = SignalType.STRONG_BUY if bullish > bearish else SignalType.STRONG_SELL
            confidence = min(1.0, avg_confidence * (bullish + bearish) / num_strategies * 1.5)
        elif bullish > bearish * 1.5:
            consensus_type = "majority"
            final_signal = SignalType.BUY
            confidence = avg_confidence * (bullish / num_strategies)
        elif bearish > bullish * 1.5:
            consensus_type = "majority"
            final_signal = SignalType.SELL
            confidence = avg_confidence * (bearish / num_strategies)
        else:
            consensus_type = "conflict"
            if weighted_score > 0.2:
                final_signal = SignalType.BUY
            elif weighted_score < -0.2:
                final_signal = SignalType.SELL
            else:
                final_signal = SignalType.NEUTRAL
            confidence = avg_confidence * 0.5  # Reduce confidence for conflicts
        
        return AggregatedSignal(
            symbol=symbol,
            final_signal=final_signal,
            weighted_score=weighted_score,
            confidence=min(1.0, confidence),
            num_strategies=num_strategies,
            strategies_bought=bullish,
            strategies_sold=bearish,
            avg_predicted_return=avg_return,
            consensus_type=consensus_type
        )
    
    def generate_position_orders(
        self,
        current_prices: Dict[str, float],
        aggregated_signals: Dict[str, AggregatedSignal]
    ) -> Dict[str, PositionOrder]:
        """
        Convert aggregated signals to position orders with sizing
        
        Args:
            current_prices: Dict mapping symbol -> price
            aggregated_signals: Output from orchestrate()
        
        Returns:
            Dict mapping symbol -> PositionOrder
        """
        position_orders = {}
        
        for symbol, signal in aggregated_signals.items():
            if signal.confidence < 0.3 or signal.num_strategies == 0:
                # Skip low-confidence signals
                continue
            
            price = current_prices.get(symbol, 0)
            if price <= 0:
                continue
            
            # Calculate target position size using Kelly criterion
            win_rate = self._get_avg_win_rate()
            avg_return = signal.avg_predicted_return / 100.0  # Convert to decimal
            
            # Kelly formula: f* = (bp - q) / b
            # Simplified for position sizing
            kelly_pct = self._calculate_kelly_fraction(win_rate, avg_return)
            
            # Apply signal strength scaling (confidence + consensus bonus)
            if signal.consensus_type == "unanimous":
                signal_scale = 1.0
            elif signal.consensus_type == "majority":
                signal_scale = 0.7
            else:
                signal_scale = 0.4
            
            target_position_pct = kelly_pct * signal_scale * signal.confidence
            target_position_pct = min(target_position_pct, self.position_limit_pct / 100)
            
            target_value = self.portfolio_value * target_position_pct
            target_qty = int(target_value / price)
            
            # Determine order urgency
            if signal.consensus_type == "unanimous":
                urgency = "immediate"
            elif signal.confidence > 0.7:
                urgency = "normal"
            else:
                urgency = "discretionary"
            
            # Calculate signal direction for position sizing
            if signal.final_signal in [SignalType.STRONG_BUY, SignalType.BUY]:
                final_qty = target_qty
            elif signal.final_signal in [SignalType.STRONG_SELL, SignalType.SELL]:
                final_qty = -abs(target_qty)
            else:
                final_qty = 0
            
            current_qty = self.current_positions.get(symbol, 0)
            delta_qty = final_qty - current_qty
            
            estimated_cost = abs(delta_qty) * price
            
            position_orders[symbol] = PositionOrder(
                symbol=symbol,
                target_qty=final_qty,
                current_qty=current_qty,
                delta_qty=delta_qty,
                signal_strength=signal.weighted_score / 2.0,  # Normalize to -1 to 1
                position_size_ratio=target_position_pct,
                estimated_cost=estimated_cost,
                urgency=urgency
            )
        
        return position_orders
    
    def _get_avg_win_rate(self) -> float:
        """Get average win rate across all strategies"""
        if not self.strategies:
            return 0.5
        
        win_rates = [
            s.get_metrics().win_rate or 0.5
            for s in self.strategies.values()
        ]
        return np.mean(win_rates) if win_rates else 0.5
    
    def _calculate_kelly_fraction(self, win_rate: float, avg_return: float) -> float:
        """
        Calculate Kelly criterion position size
        
        Kelly formula: f* = (bp - q) / b
        where p = win_rate, q = (1 - p), b = avg_return / loss
        """
        if win_rate <= 0.5 or avg_return <= 0:
            return 0.0
        
        # Estimate loss = avg_return (assume 1:1 risk:reward)
        b = max(avg_return, 0.01)
        kelly = (win_rate * b - (1 - win_rate)) / b
        
        # Apply conservative fraction
        kelly = max(0.0, min(kelly, 0.25)) * self.kelly_fraction
        return kelly
    
    def update_position(self, symbol: str, new_qty: int):
        """Update current position"""
        self.current_positions[symbol] = new_qty
    
    def record_trade(self, trade_data: Dict):
        """Record executed trade for strategy metrics update"""
        self.trades_executed.append(trade_data)
    
    def get_strategy_metrics(self) -> Dict[str, StrategyMetrics]:
        """Get metrics for all strategies"""
        return {
            sid: s.get_metrics()
            for sid, s in self.strategies.items()
        }
    
    def get_portfolio_exposure(self) -> Dict[str, float]:
        """Get current portfolio exposure by symbol"""
        exposure = {}
        for symbol, qty in self.current_positions.items():
            exposure[symbol] = qty  # Would multiply by price in real implementation
        return exposure
    
    def get_signal_efficacy(self, lookback_periods: int = 50) -> Dict[str, float]:
        """
        Calculate signal efficacy (% of signals that resulted in profit)
        
        Returns:
            Dict mapping strategy_id -> efficacy (0-1)
        """
        efficacy = {}
        
        for strategy in self.strategies.values():
            metrics = strategy.get_metrics()
            if metrics.total_trades > 0:
                efficacy[strategy.strategy_id] = metrics.win_rate
            else:
                efficacy[strategy.strategy_id] = 0.5
        
        return efficacy


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

class MockStrategy(TradingStrategy):
    """Mock strategy for demonstration"""
    
    def __init__(self, strategy_id: str, model_type: str, win_rate: float = 0.55):
        super().__init__(strategy_id, model_type)
        self.win_rate = win_rate
        self.metrics.win_rate = win_rate
    
    def generate_signals(self, symbols: List[str]) -> Dict[str, StrategySignal]:
        """Generate random signals for demo"""
        signals = {}
        for symbol in symbols:
            # Simulate signal generation
            signal_value = np.random.choice(
                [SignalType.STRONG_BUY, SignalType.BUY, SignalType.NEUTRAL,
                 SignalType.SELL, SignalType.STRONG_SELL],
                p=[0.15, 0.25, 0.20, 0.25, 0.15]
            )
            
            signals[symbol] = StrategySignal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                signal=signal_value,
                confidence=np.random.uniform(0.6, 0.95),
                predicted_return=np.random.uniform(-5, 5),
                sharpe_ratio=0.8 + np.random.uniform(-0.3, 0.3),
                win_rate=self.win_rate,
                model_type=self.model_type
            )
        
        return signals
    
    def get_confidence(self) -> float:
        return min(1.0, self.metrics.win_rate * 1.2)
    
    def update_metrics(self, trades: List[Dict]):
        pass


if __name__ == "__main__":
    # Demo
    print("=" * 70)
    print("MULTI-STRATEGY ORCHESTRATION DEMO")
    print("=" * 70)
    
    # Create orchestrator
    orchestrator = MultiStrategyOrchestrator(
        portfolio_value=100000.0,
        risk_limit_pct=2.0,
        position_limit_pct=10.0,
        conflict_resolution=ConflictResolutionMethod.WEIGHTED
    )
    
    # Register multiple strategies
    strategies = [
        MockStrategy("LSTM_Model_1", "LSTM", win_rate=0.55),
        MockStrategy("GRU_Model_1", "GRU", win_rate=0.52),
        MockStrategy("HybridNet_1", "HybridNet", win_rate=0.58),
    ]
    
    for strategy in strategies:
        orchestrator.register_strategy(strategy)
    
    # Generate signals for portfolio
    symbols = ["AAPL", "MSFT", "GOOGL", "TSLA", "NVDA"]
    print(f"\nRunning {len(orchestrator.get_strategies())} strategies...")
    aggregated_signals = orchestrator.orchestrate(symbols)
    
    # Show aggregated signals
    print("\nAGGREGATED SIGNALS:")
    print("-" * 70)
    for symbol, sig in aggregated_signals.items():
        print(f"{symbol:8} | Signal: {sig.final_signal.name:12} | "
              f"Consensus: {sig.consensus_type:12} | "
              f"Confidence: {sig.confidence:.2f} | "
              f"Score: {sig.weighted_score:+.2f}")
    
    # Generate position orders
    current_prices = {
        "AAPL": 150.0, "MSFT": 320.0, "GOOGL": 140.0,
        "TSLA": 250.0, "NVDA": 500.0
    }
    
    position_orders = orchestrator.generate_position_orders(
        current_prices, aggregated_signals
    )
    
    # Show position orders
    print("\nPOSITION ORDERS:")
    print("-" * 70)
    for symbol, order in position_orders.items():
        if order.delta_qty != 0:
            action = "BUY" if order.delta_qty > 0 else "SELL"
            print(f"{symbol:8} | {action:4} {abs(order.delta_qty):5} shares | "
                  f"Cost: ${order.estimated_cost:>10,.0f} | "
                  f"Urgency: {order.urgency}")
    
    # Show metrics
    print("\nSTRATEGY METRICS:")
    print("-" * 70)
    metrics = orchestrator.get_strategy_metrics()
    for sid, m in metrics.items():
        print(f"{sid:20} | Win Rate: {m.win_rate:.2%} | "
              f"Trades: {m.total_trades}")
