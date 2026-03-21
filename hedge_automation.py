"""
PHASE 4 MODULE 7: Hedge Automation Framework
=============================================

Automated options-based hedging strategy recommendation and execution engine.
Supports collar, protective put, straddle, and custom hedging strategies.
Integrates with Black-Scholes pricing for cost-benefit analysis.

Author: QuantNeuro Trading System
Version: 4.0
"""

import numpy as np
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Callable
from datetime import datetime, timedelta
from enum import Enum
from abc import ABC, abstractmethod
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS & DATA CLASSES
# ============================================================================

class HedgeType(Enum):
    """Supported hedging strategies"""
    COLLAR = "collar"  # Buy put + sell call (bounded risk/reward)
    PROTECTIVE_PUT = "protective_put"  # Buy put only (full upside, downside protection)
    STRADDLE = "straddle"  # Buy call + buy put (profit on move either direction)
    STRANGLE = "strangle"  # Buy OTM call + buy OTM put (cheaper straddle)
    PUT_SPREAD = "put_spread"  # Buy put + sell put (defined risk, cheaper)
    CALL_SPREAD = "call_spread"  # Buy call + sell call (defined profit, capped upside)
    IRON_CONDOR = "iron_condor"  # Sell call spread + sell put spread


class ApprovalStatus(Enum):
    """Hedge execution approval workflow"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    CANCELLED = "cancelled"


@dataclass
class OptionGreeks:
    """Option price Greeks (sensitivities)"""
    delta: float  # Rate of change vs spot price
    gamma: float  # Rate of change of delta
    vega: float  # Rate of change vs implied volatility (per 1% IV)
    theta: float  # Rate of change vs time (per day)
    rho: float  # Rate of change vs interest rate


@dataclass
class OptionPricing:
    """Option price and Greeks"""
    call_price: float
    put_price: float
    call_greeks: OptionGreeks
    put_greeks: OptionGreeks
    implied_vol: float
    expiry_days: int


@dataclass
class HedgeRecommendation:
    """Hedge strategy recommendation"""
    symbol: str
    hedge_type: HedgeType
    position_qty: int
    position_price: float
    current_price: float
    
    # Strategy details
    long_call_strike: float
    long_put_strike: float
    short_call_strike: Optional[float] = None
    short_put_strike: Optional[float] = None
    
    # Cost-benefit
    hedge_cost: float  # Total premium paid
    hedge_benefit: float  # Max loss prevention
    cost_as_pct_of_position: float  # Hedge cost / position value
    breakeven_price: float
    max_loss: float
    max_gain: float
    
    # Analysis
    time_to_expiry: int  # days
    expected_cost_benefit_ratio: float  # benefit / cost
    confidence_score: float  # 0-1, how good is this hedge
    
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = None
    executed_at: Optional[datetime] = None


@dataclass
class AuditTrail:
    """Immutable audit record for hedge decisions"""
    timestamp: datetime
    symbol: str
    hedge_type: HedgeType
    decision: str  # "recommended", "approved", "rejected", "executed"
    rationale: str
    recommended_by: str  # System or user
    approved_by: Optional[str] = None
    parameters: Dict = None


# ============================================================================
# BLACK-SCHOLES OPTION PRICING
# ============================================================================

class BlackScholesCalculator:
    """Black-Scholes option pricing model with Greeks calculation"""
    
    # Risk-free rate (annual)
    DEFAULT_RISK_FREE_RATE = 0.05
    
    @staticmethod
    def normal_cdf(x: float) -> float:
        """Cumulative normal distribution"""
        return 0.5 * (1 + np.tanh(np.sqrt(2 / np.pi) * (x + 0.044715 * x**3)))
    
    @staticmethod
    def normal_pdf(x: float) -> float:
        """Probability density function"""
        return np.exp(-0.5 * x**2) / np.sqrt(2 * np.pi)
    
    @classmethod
    def price_option(cls, spot: float, strike: float, time_to_expiry: float,
                    volatility: float, option_type: str = "call",
                    risk_free_rate: float = DEFAULT_RISK_FREE_RATE) -> float:
        """
        Black-Scholes option pricing formula
        
        Args:
            spot: Current stock price
            strike: Strike price
            time_to_expiry: Time to expiry (in years)
            volatility: Implied volatility (annual, as decimal)
            option_type: "call" or "put"
            risk_free_rate: Risk-free rate (annual)
        
        Returns:
            Option price
        """
        if time_to_expiry <= 0:
            if option_type == "call":
                return max(spot - strike, 0)
            else:
                return max(strike - spot, 0)
        
        d1 = (np.log(spot / strike) + (risk_free_rate + 0.5 * volatility**2) * time_to_expiry) \
             / (volatility * np.sqrt(time_to_expiry))
        d2 = d1 - volatility * np.sqrt(time_to_expiry)
        
        if option_type == "call":
            price = spot * cls.normal_cdf(d1) - strike * np.exp(-risk_free_rate * time_to_expiry) * cls.normal_cdf(d2)
        else:  # put
            price = strike * np.exp(-risk_free_rate * time_to_expiry) * cls.normal_cdf(-d2) - spot * cls.normal_cdf(-d1)
        
        return max(price, 0)  # Prices can't be negative
    
    @classmethod
    def calculate_greeks(cls, spot: float, strike: float, time_to_expiry: float,
                        volatility: float, option_type: str = "call",
                        risk_free_rate: float = DEFAULT_RISK_FREE_RATE) -> OptionGreeks:
        """
        Calculate option Greeks (price sensitivities)
        
        Returns:
            OptionGreeks: delta, gamma, vega, theta, rho
        """
        if time_to_expiry <= 0:
            if option_type == "call":
                delta = 1.0 if spot > strike else 0.0
            else:
                delta = -1.0 if spot < strike else 0.0
            return OptionGreeks(delta=delta, gamma=0, vega=0, theta=0, rho=0)
        
        d1 = (np.log(spot / strike) + (risk_free_rate + 0.5 * volatility**2) * time_to_expiry) \
             / (volatility * np.sqrt(time_to_expiry))
        d2 = d1 - volatility * np.sqrt(time_to_expiry)
        
        # Delta: d(option_price)/d(spot)
        if option_type == "call":
            delta = cls.normal_cdf(d1)
        else:
            delta = cls.normal_cdf(d1) - 1
        
        # Gamma: d(delta)/d(spot)
        gamma = cls.normal_pdf(d1) / (spot * volatility * np.sqrt(time_to_expiry))
        
        # Vega: d(option_price)/d(volatility) per 1% change
        vega = spot * cls.normal_pdf(d1) * np.sqrt(time_to_expiry) / 100
        
        # Theta: d(option_price)/d(time) per day
        if option_type == "call":
            theta = (-spot * cls.normal_pdf(d1) * volatility / (2 * np.sqrt(time_to_expiry)) -
                    risk_free_rate * strike * np.exp(-risk_free_rate * time_to_expiry) * cls.normal_cdf(d2)) / 365
        else:
            theta = (-spot * cls.normal_pdf(d1) * volatility / (2 * np.sqrt(time_to_expiry)) +
                    risk_free_rate * strike * np.exp(-risk_free_rate * time_to_expiry) * cls.normal_cdf(-d2)) / 365
        
        # Rho: d(option_price)/d(interest_rate) per 1% change
        if option_type == "call":
            rho = strike * time_to_expiry * np.exp(-risk_free_rate * time_to_expiry) * cls.normal_cdf(d2) / 100
        else:
            rho = -strike * time_to_expiry * np.exp(-risk_free_rate * time_to_expiry) * cls.normal_cdf(-d2) / 100
        
        return OptionGreeks(delta=delta, gamma=gamma, vega=vega, theta=theta, rho=rho)


# ============================================================================
# HEDGE RECOMMENDATION ENGINE
# ============================================================================

class HedgeRecommenderEngine:
    """
    Automated hedge strategy recommendation engine.
    Analyzes positions and recommends optimal hedging strategies.
    """
    
    def __init__(self, risk_free_rate: float = 0.05):
        self.risk_free_rate = risk_free_rate
        self.bs = BlackScholesCalculator()
        self.audit_trail: List[AuditTrail] = []
    
    def recommend_hedge(self, symbol: str, position_qty: int, position_entry_price: float,
                       current_price: float, volatility: float, days_to_expiry: int = 30,
                       max_hedge_cost_pct: float = 0.02) -> Optional[HedgeRecommendation]:
        """
        Recommend hedge strategy for a position
        
        Args:
            symbol: Stock ticker
            position_qty: Number of shares held
            position_entry_price: Price at which position was acquired
            current_price: Current stock price
            volatility: Implied volatility (as decimal, e.g., 0.20 for 20%)
            days_to_expiry: Days to option expiry
            max_hedge_cost_pct: Max acceptable hedge cost as % of position value
        
        Returns:
            HedgeRecommendation with best strategy
        """
        position_value = position_qty * current_price
        unrealized_pnl = (current_price - position_entry_price) * position_qty
        unrealized_pnl_pct = unrealized_pnl / (position_entry_price * position_qty)
        
        time_to_expiry_years = days_to_expiry / 365.0
        
        # Generate candidate strategies
        candidates = []
        
        # 1. Protective Put: Buy put, keep upside
        if unrealized_pnl_pct > 0.05:  # Only hedge if significant gains
            put_strike = current_price * 0.95  # 5% below current
            put_price = self.bs.price_option(current_price, put_strike, time_to_expiry_years,
                                           volatility, "put", self.risk_free_rate)
            total_cost = put_price * position_qty
            cost_pct = total_cost / position_value
            
            if cost_pct <= max_hedge_cost_pct:
                candidates.append(HedgeRecommendation(
                    symbol=symbol, hedge_type=HedgeType.PROTECTIVE_PUT,
                    position_qty=position_qty, position_price=position_entry_price,
                    current_price=current_price,
                    long_put_strike=put_strike, long_call_strike=None,
                    hedge_cost=total_cost, hedge_benefit=unrealized_pnl,
                    cost_as_pct_of_position=cost_pct,
                    breakeven_price=current_price - put_price,
                    max_loss=position_qty * (put_strike - position_entry_price),
                    max_gain=float('inf'),
                    time_to_expiry=days_to_expiry,
                    expected_cost_benefit_ratio=unrealized_pnl / total_cost if total_cost > 0 else 0,
                    confidence_score=0.85
                ))
        
        # 2. Collar: Buy put, sell call (bounded risk, no upside)
        if unrealized_pnl_pct > 0.10:  # Only for significant unrealized gains
            put_strike = current_price * 0.95
            call_strike = current_price * 1.05
            
            put_price = self.bs.price_option(current_price, put_strike, time_to_expiry_years,
                                           volatility, "put", self.risk_free_rate)
            call_price = self.bs.price_option(current_price, call_strike, time_to_expiry_years,
                                            volatility, "call", self.risk_free_rate)
            
            net_cost = (put_price - call_price) * position_qty
            cost_pct = net_cost / position_value if net_cost > 0 else 0
            
            if net_cost < 0 or cost_pct <= max_hedge_cost_pct:  # Net debit or credit
                protected_gain = (call_strike - position_entry_price) * position_qty
                candidates.append(HedgeRecommendation(
                    symbol=symbol, hedge_type=HedgeType.COLLAR,
                    position_qty=position_qty, position_price=position_entry_price,
                    current_price=current_price,
                    long_put_strike=put_strike, long_call_strike=call_strike,
                    short_call_strike=call_strike,
                    hedge_cost=max(net_cost, 0),
                    hedge_benefit=protected_gain - position_entry_price * position_qty,
                    cost_as_pct_of_position=max(cost_pct, 0),
                    breakeven_price=position_entry_price,
                    max_loss=position_qty * (put_strike - position_entry_price),
                    max_gain=position_qty * (call_strike - position_entry_price),
                    time_to_expiry=days_to_expiry,
                    expected_cost_benefit_ratio=(protected_gain - position_entry_price * position_qty) / max(net_cost, 1),
                    confidence_score=0.90
                ))
        
        # 3. Straddle: Own upside and downside
        if unrealized_pnl_pct < -0.10:  # Protect underwater positions
            call_strike = current_price
            put_strike = current_price
            
            call_price = self.bs.price_option(current_price, call_strike, time_to_expiry_years,
                                            volatility, "call", self.risk_free_rate)
            put_price = self.bs.price_option(current_price, put_strike, time_to_expiry_years,
                                           volatility, "put", self.risk_free_rate)
            
            total_cost = (call_price + put_price) * position_qty
            cost_pct = total_cost / position_value
            
            if cost_pct <= max_hedge_cost_pct:
                candidates.append(HedgeRecommendation(
                    symbol=symbol, hedge_type=HedgeType.STRADDLE,
                    position_qty=position_qty, position_price=position_entry_price,
                    current_price=current_price,
                    long_call_strike=call_strike, long_put_strike=put_strike,
                    hedge_cost=total_cost,
                    hedge_benefit=abs(unrealized_pnl),
                    cost_as_pct_of_position=cost_pct,
                    breakeven_price=current_price,
                    max_loss=total_cost,
                    max_gain=float('inf'),
                    time_to_expiry=days_to_expiry,
                    expected_cost_benefit_ratio=abs(unrealized_pnl) / total_cost if total_cost > 0 else 0,
                    confidence_score=0.75
                ))
        
        # Select best strategy (highest confidence + best cost-benefit)
        if not candidates:
            logger.warning(f"No suitable hedge found for {symbol} - cost constraints too tight")
            return None
        
        best = max(candidates, key=lambda x: x.confidence_score * x.expected_cost_benefit_ratio)
        best.created_at = datetime.now()
        
        # Log audit trail
        self._audit_log(
            symbol=symbol, hedge_type=best.hedge_type,
            decision="recommended",
            rationale=f"Cost-benefit ratio: {best.expected_cost_benefit_ratio:.2f}x, Confidence: {best.confidence_score:.2f}"
        )
        
        return best
    
    def approve_hedge(self, recommendation: HedgeRecommendation, approved_by: str = "system"):
        """Approve hedge for execution"""
        recommendation.approval_status = ApprovalStatus.APPROVED
        self._audit_log(
            symbol=recommendation.symbol, hedge_type=recommendation.hedge_type,
            decision="approved", rationale=f"Approved by {approved_by}",
            approved_by=approved_by
        )
    
    def reject_hedge(self, recommendation: HedgeRecommendation, reason: str):
        """Reject hedge"""
        recommendation.approval_status = ApprovalStatus.REJECTED
        self._audit_log(
            symbol=recommendation.symbol, hedge_type=recommendation.hedge_type,
            decision="rejected", rationale=reason
        )
    
    def execute_hedge(self, recommendation: HedgeRecommendation):
        """Mark hedge as executed"""
        recommendation.approval_status = ApprovalStatus.EXECUTED
        recommendation.executed_at = datetime.now()
        self._audit_log(
            symbol=recommendation.symbol, hedge_type=recommendation.hedge_type,
            decision="executed", rationale="Hedge executed and legs placed with broker"
        )
    
    def _audit_log(self, symbol: str, hedge_type: HedgeType, decision: str,
                   rationale: str, approved_by: Optional[str] = None):
        """Add entry to immutable audit trail"""
        entry = AuditTrail(
            timestamp=datetime.now(),
            symbol=symbol,
            hedge_type=hedge_type,
            decision=decision,
            rationale=rationale,
            recommended_by="HedgeRecommenderEngine",
            approved_by=approved_by
        )
        self.audit_trail.append(entry)
        logger.info(f"Audit: {symbol} {hedge_type.value} {decision} - {rationale}")


# ============================================================================
# HEDGE EXECUTION ENGINE
# ============================================================================

class HedgeExecutor:
    """
    Executes approved hedge strategies.
    Integrates with broker adapter for options order placement.
    """
    
    def __init__(self, broker_adapter):
        """
        Args:
            broker_adapter: BrokerAdapter instance with options support
        """
        self.broker = broker_adapter
        self.executed_hedges: List[HedgeRecommendation] = []
    
    def execute_collar(self, recommendation: HedgeRecommendation) -> bool:
        """
        Execute collar: Buy put + Sell call
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # 1. Buy put
            put_order = self.broker.place_options_order(
                symbol=recommendation.symbol,
                option_type="put",
                strike=recommendation.long_put_strike,
                expiry_days=recommendation.time_to_expiry,
                qty=recommendation.position_qty,
                side="BUY"
            )
            
            # 2. Sell call
            call_order = self.broker.place_options_order(
                symbol=recommendation.symbol,
                option_type="call",
                strike=recommendation.long_call_strike,
                expiry_days=recommendation.time_to_expiry,
                qty=recommendation.position_qty,
                side="SELL"
            )
            
            logger.info(f"Collar executed: BUY {recommendation.position_qty} puts @ {recommendation.long_put_strike}, "
                       f"SELL {recommendation.position_qty} calls @ {recommendation.long_call_strike}")
            
            self.executed_hedges.append(recommendation)
            return True
        
        except Exception as e:
            logger.error(f"Collar execution failed: {e}")
            return False
    
    def execute_protective_put(self, recommendation: HedgeRecommendation) -> bool:
        """Execute protective put: Buy put"""
        try:
            put_order = self.broker.place_options_order(
                symbol=recommendation.symbol,
                option_type="put",
                strike=recommendation.long_put_strike,
                expiry_days=recommendation.time_to_expiry,
                qty=recommendation.position_qty,
                side="BUY"
            )
            
            logger.info(f"Protective put executed: BUY {recommendation.position_qty} puts @ {recommendation.long_put_strike}")
            self.executed_hedges.append(recommendation)
            return True
        
        except Exception as e:
            logger.error(f"Protective put execution failed: {e}")
            return False


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    # Initialize calculator
    bs = BlackScholesCalculator()
    
    # Price a call option
    spot, strike, ttexp, vol = 100.0, 105.0, 30/365, 0.25
    call_price = bs.price_option(spot, strike, ttexp, vol, "call")
    call_greeks = bs.calculate_greeks(spot, strike, ttexp, vol, "call")
    
    print(f"Call Option Pricing (S={spot}, K={strike}, T={ttexp:.4f}, σ={vol})")
    print(f"  Call Price: ${call_price:.2f}")
    print(f"  Delta: {call_greeks.delta:.4f}, Gamma: {call_greeks.gamma:.4f}")
    print(f"  Vega: {call_greeks.vega:.4f}, Theta: {call_greeks.theta:.4f}")
    print()
    
    # Recommend hedge strategy
    engine = HedgeRecommenderEngine()
    
    # Scenario: Long 1000 shares of AAPL, average cost $150, current $165 (10% gain)
    recommendation = engine.recommend_hedge(
        symbol="AAPL",
        position_qty=1000,
        position_entry_price=150.0,
        current_price=165.0,
        volatility=0.25,
        days_to_expiry=30,
        max_hedge_cost_pct=0.02
    )
    
    if recommendation:
        print(f"Hedge Recommendation for {recommendation.symbol}:")
        print(f"  Strategy: {recommendation.hedge_type.value}")
        print(f"  Position: {recommendation.position_qty} shares @ ${recommendation.position_price}")
        print(f"  Current Price: ${recommendation.current_price}")
        print(f"  Hedge Cost: ${recommendation.hedge_cost:,.2f} ({recommendation.cost_as_pct_of_position:.2%})")
        print(f"  Max Loss: ${recommendation.max_loss:,.2f}")
        print(f"  Max Gain: ${recommendation.max_gain:,.2f}")
        print(f"  Cost-Benefit Ratio: {recommendation.expected_cost_benefit_ratio:.2f}x")
        print(f"  Confidence: {recommendation.confidence_score:.2%}")
        print()
        
        # Approve and execute
        engine.approve_hedge(recommendation)
        engine.execute_hedge(recommendation)
        print(f"Recommendation approved and executed")
        print(f"Audit trail entries: {len(engine.audit_trail)}")
