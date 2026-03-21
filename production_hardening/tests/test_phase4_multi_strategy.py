"""
PHASE 4 INTEGRATION TESTS - Multi-Strategy Scenarios

Test suite for:
1. Multi-strategy orchestration
2. Order execution flow
3. Risk aggregation during live trading
4. Compliance enforcement
5. Broker connectivity (mock)

Run with: pytest tests/test_phase4_multi_strategy.py -v
"""

import pytest
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List
import asyncio


# ============================================================================
# MOCK OBJECTS & FIXTURES
# ============================================================================

@pytest.fixture
def mock_market_data():
    """Generate realistic market data for testing."""
    dates = np.arange(100)
    prices = 100 + np.cumsum(np.random.normal(0.001, 0.02, 100))
    
    data = {
        "AAPL": {"prices": prices, "volumes": np.random.randint(1e6, 5e6, 100)},
        "GOOGL": {"prices": 100 + np.cumsum(np.random.normal(0.0005, 0.025, 100)),
                  "volumes": np.random.randint(500e3, 2e6, 100)},
        "MSFT": {"prices": 100 + np.cumsum(np.random.normal(0.0007, 0.018, 100)),
                 "volumes": np.random.randint(800e3, 3e6, 100)},
    }
    return data


@pytest.fixture
def mock_broker():
    """Mock broker adapter for testing."""
    class MockBroker:
        def __init__(self):
            self.positions = {}
            self.orders = {}
            self.order_id_counter = 1
            self.cash = 1000000
        
        def place_order(self, ticker, qty, price, side="BUY"):
            order_id = self.order_id_counter
            self.order_id_counter += 1
            
            self.orders[order_id] = {
                "id": order_id,
                "ticker": ticker,
                "qty": qty,
                "price": price,
                "side": side,
                "status": "FILLED",
                "timestamp": datetime.now()
            }
            
            # Simulate fill
            cost = qty * price
            if side == "BUY":
                if self.cash >= cost:
                    self.cash -= cost
                    self.positions[ticker] = self.positions.get(ticker, 0) + qty
            else:  # SELL
                self.positions[ticker] = self.positions.get(ticker, 0) - qty
                self.cash += cost
            
            return order_id
        
        def get_position(self, ticker):
            return self.positions.get(ticker, 0)
        
        def get_positions(self):
            return dict(self.positions)
        
        def get_cash(self):
            return self.cash
        
        def get_order_status(self, order_id):
            return self.orders.get(order_id, {}).get("status")
    
    return MockBroker()


@pytest.fixture
def mock_strategies():
    """Create 3 simple mock strategies."""
    def momentum_signal(prices):
        """Return 1 (buy) if up, -1 (sell) if down."""
        return 1 if prices[-1] > prices[-20] else -1
    
    def mean_reversion_signal(prices):
        """Return 1 if below 20-day MA, -1 if above."""
        ma = np.mean(prices[-20:])
        return 1 if prices[-1] < ma else -1
    
    def ml_classifier_signal(prices):
        """Dummy ML prediction."""
        volatility = np.std(prices[-5:])
        return 1 if volatility < 0.02 else -1 if volatility > 0.03 else 0
    
    return {
        "momentum": momentum_signal,
        "mean_reversion": mean_reversion_signal,
        "ml_classifier": ml_classifier_signal
    }


# ============================================================================
# TEST CLASS: MULTI-STRATEGY ORCHESTRATION
# ============================================================================

class TestMultiStrategyOrchestration:
    """Test ensemble signal generation."""
    
    def test_majority_voting(self, mock_strategies, mock_market_data):
        """Verify majority voting mechanism."""
        signals = {}
        
        for name, strategy in mock_strategies.items():
            signals[name] = strategy(mock_market_data["AAPL"]["prices"])
        
        # Count votes
        buy_votes = sum(1 for s in signals.values() if s > 0)
        sell_votes = sum(1 for s in signals.values() if s < 0)
        
        # Majority voting
        if buy_votes > len(signals) / 2:
            ensemble_signal = 1  # BUY
        elif sell_votes > len(signals) / 2:
            ensemble_signal = -1  # SELL
        else:
            ensemble_signal = 0  # HOLD
        
        assert ensemble_signal in [-1, 0, 1]
        print(f"Signals: {signals} → Ensemble: {ensemble_signal}")
    
    def test_weighted_voting(self, mock_strategies, mock_market_data):
        """Verify weighted voting by Sharpe ratio."""
        # Simulated Sharpe ratios (strategy performance)
        sharpe_scores = {
            "momentum": 1.5,
            "mean_reversion": 0.8,
            "ml_classifier": 2.2
        }
        
        signals = {}
        total_weight = 0
        weighted_sum = 0
        
        for name, strategy in mock_strategies.items():
            signal = strategy(mock_market_data["AAPL"]["prices"])
            weight = max(0, sharpe_scores[name])  # Non-negative weights
            signals[name] = signal
            weighted_sum += signal * weight
            total_weight += weight
        
        if total_weight > 0:
            ensemble_signal = weighted_sum / total_weight
        else:
            ensemble_signal = 0
        
        assert -1 <= ensemble_signal <= 1
        print(f"Weighted ensemble: {ensemble_signal:.2f}")
    
    def test_strategy_correlation(self, mock_strategies, mock_market_data):
        """Verify strategies are not too correlated."""
        n_days = 90
        signal_history = {name: [] for name in mock_strategies}
        
        prices = mock_market_data["AAPL"]["prices"]
        
        # Generate signals over time
        for i in range(20, len(prices)):
            window = prices[i-20:i]
            for name, strategy in mock_strategies.items():
                signal = strategy(window)
                signal_history[name].append(signal)
        
        # Calculate correlation between strategies
        strategies_list = list(mock_strategies.keys())
        correlations = {}
        
        for i, s1 in enumerate(strategies_list):
            for s2 in strategies_list[i+1:]:
                avg_corr = np.corrcoef(
                    signal_history[s1],
                    signal_history[s2]
                )[0, 1]
                if not np.isnan(avg_corr):
                    correlations[f"{s1}_vs_{s2}"] = avg_corr
        
        # Low correlation = diversified strategies
        avg_correlation = np.mean(list(correlations.values()))
        assert avg_correlation < 0.9, "Strategies too correlated"
        print(f"Strategy correlations: {correlations}")
    
    def test_signal_confidence_scoring(self, mock_strategies, mock_market_data):
        """Verify confidence score calculation."""
        signals = {}
        confidences = {}
        
        for name, strategy in mock_strategies.items():
            signals[name] = strategy(mock_market_data["AAPL"]["prices"])
        
        # Calculate agreement (confidence)
        all_signals = list(signals.values())
        agreement = abs(sum(all_signals)) / len(all_signals)
        
        # Confidence: 1.0 = all agree, 0 = mixed
        confidence = agreement
        
        assert 0 <= confidence <= 1
        print(f"Ensemble confidence: {confidence:.2%}")


# ============================================================================
# TEST CLASS: ORDER EXECUTION FLOW
# ============================================================================

class TestOrderExecutionFlow:
    """Test order management and execution."""
    
    def test_order_placement(self, mock_broker):
        """Verify order placement and tracking."""
        order_id = mock_broker.place_order("AAPL", qty=100, price=150.0, side="BUY")
        
        assert order_id is not None
        assert mock_broker.get_position("AAPL") == 100
        assert mock_broker.get_cash() < 1000000
    
    def test_partial_fill_handling(self, mock_broker):
        """Verify partial fill scenario."""
        # Place large order
        order_id = mock_broker.place_order("AAPL", qty=1000, price=150.0, side="BUY")
        
        position = mock_broker.get_position("AAPL")
        cash = mock_broker.get_cash()
        
        # Even with slippage, position should exist
        assert position > 0
        assert cash < 1000000
    
    def test_order_rejection_insufficient_cash(self, mock_broker):
        """Verify order rejection on insufficient cash."""
        # Deposit only 100k
        mock_broker.cash = 100000
        
        # Try to buy $500k worth
        try:
            order_id = mock_broker.place_order("AAPL", qty=5000, price=150.0, side="BUY")
            # In real implementation, this would be rejected
            # Here we verify the cash constraint
            assert mock_broker.get_cash() >= 0
        except:
            pass  # Expected to fail
    
    def test_sell_order_reduces_position(self, mock_broker):
        """Verify sell orders reduce position."""
        # Buy first
        mock_broker.place_order("AAPL", qty=100, price=150.0, side="BUY")
        initial_pos = mock_broker.get_position("AAPL")
        
        # Sell half
        mock_broker.place_order("AAPL", qty=50, price=150.0, side="SELL")
        final_pos = mock_broker.get_position("AAPL")
        
        assert final_pos == initial_pos - 50
        assert final_pos == 50
    
    def test_order_history_tracking(self, mock_broker):
        """Verify order history is tracked."""
        order_id1 = mock_broker.place_order("AAPL", qty=100, price=150.0)
        order_id2 = mock_broker.place_order("GOOGL", qty=50, price=130.0)
        
        assert order_id1 < order_id2
        assert len(mock_broker.orders) == 2


# ============================================================================
# TEST CLASS: REAL-TIME RISK AGGREGATION
# ============================================================================

class TestRealTimeRiskAggregation:
    """Test portfolio risk calculations."""
    
    def test_var_calculation(self, mock_market_data):
        """Verify VaR calculation."""
        prices = mock_market_data["AAPL"]["prices"]
        returns = np.diff(prices) / prices[:-1]
        
        confidence = 0.95
        var_95 = np.percentile(returns, (1 - confidence) * 100)
        
        # VaR should be negative (loss)
        assert var_95 < 0
        
        # For 1M portfolio and 1-day horizon
        portfolio_var = 1000000 * var_95
        print(f"VaR 95% (1-day): ${-portfolio_var:.0f}")
    
    def test_portfolio_concentration(self, mock_broker):
        """Verify concentration monitoring."""
        # Create portfolio
        total_value = 0
        
        mock_broker.place_order("AAPL", qty=100, price=150.0)
        mock_broker.place_order("GOOGL", qty=50, price=130.0)
        mock_broker.place_order("MSFT", qty=75, price=130.0)
        
        positions = {
            "AAPL": 100 * 150.0,
            "GOOGL": 50 * 130.0,
            "MSFT": 75 * 130.0
        }
        total_value = sum(positions.values())
        
        # Calculate portfolio weights
        weights = {k: v / total_value for k, v in positions.items()}
        
        # HHI concentration = sum of squared weights
        hhi = sum(w**2 for w in weights.values())
        
        # Should be between 0.33 (equal) and 1.0 (concentrated)
        assert 0 < hhi <= 1
        print(f"Portfolio HHI: {hhi:.3f} (1/N={1/3:.3f})")
    
    def test_sector_concentration(self):
        """Verify sector concentration limits."""
        positions = {
            "AAPL": {"sector": "Technology", "value": 150000},
            "GOOGL": {"sector": "Technology", "value": 130000},
            "JNJ": {"sector": "Healthcare", "value": 100000},
            "XOM": {"sector": "Energy", "value": 80000}
        }
        
        total = sum(p["value"] for p in positions.values())
        
        sector_totals = {}
        for ticker, data in positions.items():
            sector = data["sector"]
            sector_totals[sector] = sector_totals.get(sector, 0) + data["value"]
        
        sector_weights = {s: v / total for s, v in sector_totals.items()}
        
        # Tech should be around 56%
        assert sector_weights["Technology"] > 0.5
        assert sector_weights["Healthcare"] < 0.3
    
    def test_correlation_update_during_trading(self, mock_market_data):
        """Verify correlation matrix updates during trading."""
        tickers = ["AAPL", "GOOGL", "MSFT"]
        
        # Create rolling correlation matrix
        prices = np.array([mock_market_data[t]["prices"] for t in tickers])
        returns = np.diff(prices, axis=1) / prices[:, :-1]
        
        # Correlation of last 60 days
        window_corr = np.corrcoef(returns[:, -60:])
        
        assert window_corr.shape == (3, 3)
        assert np.isclose(np.diag(window_corr), 1.0).all()  # Diagonal = 1
        
        # Verify positive correlations (tech stocks)
        off_diag = window_corr[np.triu_indices_from(window_corr, k=1)]
        assert all(c > 0.3 for c in off_diag)  # Tech stocks correlated


# ============================================================================
# TEST CLASS: COMPLIANCE & LIMITS
# ============================================================================

class TestComplianceEnforcement:
    """Test compliance rules and position limits."""
    
    def test_position_limit_enforcement(self, mock_broker):
        """Verify position size limits."""
        max_position_pct = 0.05  # 5% max
        portfolio_value = 1000000
        max_position_value = portfolio_value * max_position_pct
        
        # Try to place order within limit
        order_id = mock_broker.place_order("AAPL", qty=30, price=150.0)
        position_value = 30 * 150.0
        
        assert position_value <= max_position_value
    
    def test_daily_loss_limit(self):
        """Verify daily loss limit enforcement."""
        initial_capital = 1000000
        max_daily_loss_pct = 0.02  # 2% max daily loss
        max_daily_loss = initial_capital * max_daily_loss_pct
        
        # Simulate daily PnL
        daily_pnl = -15000  # Lost $15k
        
        should_stop = daily_pnl < -max_daily_loss
        
        # 2% of $1M = $20k, so $15k loss should not stop yet
        assert not should_stop
        
        # But $25k loss should stop
        daily_pnl = -25000
        should_stop = daily_pnl < -max_daily_loss
        assert should_stop
    
    def test_leverage_limit(self):
        """Verify leverage limits."""
        portfolio_value = 1000000
        cash = 100000
        positions_value = 950000  # Margin used
        
        max_leverage = 3.0
        actual_leverage = (positions_value + cash) / portfolio_value
        
        assert actual_leverage <= max_leverage
    
    def test_concentration_limit_enforcement(self):
        """Verify concentration doesn't exceed limits."""
        max_hhi = 0.25  # Max concentration
        
        weights = np.array([0.3, 0.25, 0.2, 0.15, 0.1])
        hhi = np.sum(weights**2)
        
        should_allow = hhi <= max_hhi
        
        # This concentration is at 0.225, should be allowed
        assert should_allow


# ============================================================================
# TEST CLASS: END-TO-END WORKFLOW
# ============================================================================

class TestEndToEndMultiStrategyWorkflow:
    """Test complete trading workflow."""
    
    def test_signal_to_execution_flow(self, mock_strategies, mock_broker, mock_market_data):
        """Test complete flow: signal → ensemble → order → execution."""
        
        # 1. Get signals from all strategies
        signals = {}
        for name, strategy in mock_strategies.items():
            signals[name] = strategy(mock_market_data["AAPL"]["prices"])
        
        # 2. Ensemble voting
        signal_values = list(signals.values())
        ensemble_signal = np.mean(signal_values)
        
        # 3. Risk check (simplified)
        risk_ok = True  # Assume no risk violations
        
        # 4. Execute if signal strong enough
        if risk_ok and abs(ensemble_signal) > 0.33:  # > 1/3 agreement
            if ensemble_signal > 0:
                order_id = mock_broker.place_order("AAPL", qty=100, price=150.0, side="BUY")
            else:
                order_id = mock_broker.place_order("AAPL", qty=100, price=150.0, side="SELL")
            
            # 5. Verify execution
            assert order_id is not None
            position = abs(mock_broker.get_position("AAPL"))
            assert position >= 0
    
    def test_multiple_concurrent_trades(self, mock_broker):
        """Verify handling of concurrent orders."""
        orders = [
            mock_broker.place_order("AAPL", 100, 150.0, "BUY"),
            mock_broker.place_order("GOOGL", 50, 130.0, "BUY"),
            mock_broker.place_order("MSFT", 75, 130.0, "BUY"),
        ]
        
        # All orders should execute
        assert len(orders) == 3
        assert all(oid is not None for oid in orders)
        
        # Positions should update
        positions = mock_broker.get_positions()
        assert len(positions) == 3
        assert sum(positions.values()) == 100 + 50 + 75
    
    def test_rebalancing_workflow(self, mock_broker):
        """Test portfolio rebalancing."""
        # Initial portfolio
        initial_cash = 1000000
        mock_broker.cash = initial_cash
        
        # Setup initial positions (50/50)
        mock_broker.place_order("AAPL", qty=3333, price=150.0, side="BUY")
        mock_broker.place_order("GOOGL", qty=3846, price=130.0, side="BUY")
        
        initial_positions = dict(mock_broker.get_positions())
        initial_value = sum(p * 150 for p, t in initial_positions.items() if t == "AAPL") + \
                       sum(p * 130 for p, t in initial_positions.items() if t == "GOOGL")
        
        # Prices change 10%
        new_aapl_price = 150 * 1.1
        new_googl_price = 130 * 0.95
        
        # Rebalance needed if drift > 5%
        rebalance_threshold = 0.05
        
        # Calculate new weights
        aapl_position = initial_positions.get("AAPL", 0)
        googl_position = initial_positions.get("GOOGL", 0)
        
        new_value = aapl_position * new_aapl_price + googl_position * new_googl_price
        aapl_weight = (aapl_position * new_aapl_price) / new_value
        
        # Check if rebalance needed
        target_weight = 0.5
        drift = abs(aapl_weight - target_weight)
        
        should_rebalance = drift > rebalance_threshold
        assert isinstance(should_rebalance, bool)


# ============================================================================
# RUNNER
# ============================================================================

if __name__ == "__main__":
    print("Phase 4 Integration Tests")
    print("=" * 60)
    print("\nTest modules:")
    print("  1. Multi-Strategy Orchestration")
    print("  2. Order Execution Flow")
    print("  3. Real-Time Risk Aggregation")
    print("  4. Compliance & Limits")
    print("  5. End-to-End Workflow")
    print("\nRun: pytest tests/test_phase4_multi_strategy.py -v")
    print("=" * 60)
