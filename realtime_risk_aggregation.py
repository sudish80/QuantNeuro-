"""
PHASE 4 MODULE 4: Real-Time Portfolio Risk Aggregation
========================================================

Monitor portfolio-level risk, correlation breakdowns, systemic risks,
and value-at-risk in real-time during live trading.

Features:
- Dynamic correlation matrix tracking
- Sector and factor exposures
- Value-at-Risk (VaR) estimation
- Expected Shortfall (CVaR)
- Correlation breakdown detection
- Systemic risk warnings
- Hedging recommendations
- Greeks aggregation (for options portfolios)

Author: QuantNeuro Trading System
Version: 4.0
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Set
from datetime import datetime, timedelta
from enum import Enum
import numpy as np
import logging
from collections import defaultdict, deque

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS & DATA CLASSES
# ============================================================================

class RiskLevel(Enum):
    """Overall portfolio risk level"""
    LOW = "low"           # All green
    MODERATE = "moderate" # Some warnings
    ELEVATED = "elevated" # Multiple warnings
    CRITICAL = "critical" # Immediate action needed


class SectorType(Enum):
    """Market sectors for exposure tracking"""
    TECHNOLOGY = "technology"
    FINANCE = "finance"
    HEALTHCARE = "healthcare"
    ENERGY = "energy"
    CONSUMER = "consumer"
    INDUSTRIAL = "industrial"
    UTILITIES = "utilities"
    REALESTATE = "realestate"
    MATERIALS = "materials"
    TELECOM = "telecom"
    CRYPTO = "crypto"


class FactorType(Enum):
    """Risk factors for factor exposure"""
    MARKET_BETA = "market_beta"
    MOMENTUM = "momentum"
    VALUE = "value"
    QUALITY = "quality"
    GROWTH = "growth"
    VOLATILITY = "volatility"
    DIVIDEND_YIELD = "dividend_yield"
    SIZE = "size"


@dataclass
class PositionRisk:
    """Risk metrics for individual position"""
    symbol: str
    sector: Optional[SectorType]
    weight: float  # % of portfolio
    beta: float  # Market beta
    volatility: float  # Annualized volatility
    var_95: float  # Daily VaR at 95% confidence
    expected_return: float  # Expected daily return
    correlation_to_market: float


@dataclass
class SectorExposure:
    """Exposure to specific sector"""
    sector: SectorType
    notional_value: float
    weight: float  # % of portfolio
    avg_beta: float
    volatility: float
    correlation_to_market: float


@dataclass
class CorrelationBreakdown:
    """Detected correlation breakdown"""
    symbols: Tuple[str, str]
    historical_correlation: float
    recent_correlation: float
    correlation_change: float
    severity: str  # "low", "medium", "high"
    timestamp: datetime


@dataclass
class RiskWarning:
    """Portfolio risk warning"""
    warning_type: str  # e.g., "high_correlation", "concentration", "volatility"
    severity: str  # "low", "medium", "high", "critical"
    message: str
    recommendation: str
    timestamp: datetime


@dataclass
class PortfolioRiskSnapshot:
    """Comprehensive portfolio risk snapshot"""
    timestamp: datetime
    overall_risk_level: RiskLevel
    total_portfolio_value: float
    
    # VaR metrics
    var_95_daily: float  # Daily VaR at 95% confidence
    var_99_daily: float  # Daily VaR at 99% confidence
    cvar_95_daily: float  # Expected Shortfall at 95%
    
    # Exposure metrics
    gross_exposure: float
    net_exposure: float
    leverage: float
    
    # Sector concentrations
    largest_sector: SectorType
    largest_sector_weight: float
    sector_diversity: float  # 0-1, higher = more diversified
    
    # Correlation metrics
    avg_correlation: float
    max_correlation: float
    num_high_correlations: int  # Pairs with corr > 0.8
    
    # Warnings
    active_warnings: List[RiskWarning]
    correlation_breakdowns: List[CorrelationBreakdown]
    
    # Greeks
    portfolio_delta: float
    portfolio_gamma: float
    portfolio_vega: float
    portfolio_theta: float


# ============================================================================
# REAL-TIME RISK AGGREGATOR
# ============================================================================

class RealTimeRiskAggregator:
    """
    Monitor and aggregate portfolio risk in real-time
    """
    
    def __init__(
        self,
        portfolio_value: float,
        lookback_periods: int = 252,  # 1 trading year
        correlation_window: int = 20,  # 20-day rolling
        var_confidence: float = 0.95,
        max_sector_weight: float = 0.25,
        max_correlation_threshold: float = 0.8,
    ):
        """
        Args:
            portfolio_value: Total portfolio value
            lookback_periods: History for VaR calculation
            correlation_window: Rolling correlation window
            var_confidence: VaR confidence level (0.95 = 95%)
            max_sector_weight: Maximum single sector weight
            max_correlation_threshold: Alert if correlation exceeds this
        """
        self.portfolio_value = portfolio_value
        self.lookback_periods = lookback_periods
        self.correlation_window = correlation_window
        self.var_confidence = var_confidence
        self.max_sector_weight = max_sector_weight
        self.max_correlation_threshold = max_correlation_threshold
        
        # Price history for correlation tracking
        self.price_history: Dict[str, deque] = {}
        self.returns_history: Dict[str, deque] = {}
        
        # Position tracking
        self.positions: Dict[str, Dict] = {}
        self.sector_map: Dict[str, SectorType] = {}
        
        # Risk state
        self.active_warnings: List[RiskWarning] = []
        self.historical_correlations: Dict[Tuple[str, str], float] = {}
        self.correlation_breakdowns: deque = deque(maxlen=100)
        
        # Greeks tracking
        self.greeks: Dict[str, Dict[str, float]] = {}  # symbol -> {delta, gamma, vega, theta}
    
    def update_prices(self, current_prices: Dict[str, float]):
        """Update price history with latest market prices"""
        for symbol, price in current_prices.items():
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.lookback_periods)
                self.returns_history[symbol] = deque(maxlen=self.correlation_window)
            
            # Add new price
            self.price_history[symbol].append(price)
            
            # Calculate return
            if len(self.price_history[symbol]) > 1:
                prev_price = self.price_history[symbol][-2]
                ret = (price - prev_price) / prev_price
                self.returns_history[symbol].append(ret)
    
    def update_position(
        self,
        symbol: str,
        qty: int,
        price: float,
        sector: Optional[SectorType] = None,
        beta: float = 1.0
    ):
        """Update position information"""
        self.positions[symbol] = {
            "qty": qty,
            "price": price,
            "value": qty * price,
            "beta": beta,
            "sector": sector
        }
        
        if sector:
            self.sector_map[symbol] = sector
    
    def calculate_position_risk(self, symbol: str) -> Optional[PositionRisk]:
        """Calculate risk metrics for individual position"""
        if symbol not in self.positions or symbol not in self.returns_history:
            return None
        
        pos = self.positions[symbol]
        returns = list(self.returns_history[symbol])
        
        if len(returns) < 2:
            return None
        
        volatility = np.std(returns) * np.sqrt(252)  # Annualize
        weight = pos["value"] / self.portfolio_value
        
        # VaR using historical method
        var_95 = np.percentile(returns, 5) * pos["price"]
        
        # Expected return (simplified)
        expected_return = np.mean(returns)
        
        # Correlation to market (simplified: average correlation to others)
        correlations = []
        for other_symbol in self.positions:
            if other_symbol != symbol and other_symbol in self.returns_history:
                corr = self._calculate_correlation(symbol, other_symbol)
                correlations.append(corr)
        
        corr_to_market = np.mean(correlations) if correlations else 0.5
        
        return PositionRisk(
            symbol=symbol,
            sector=self.sector_map.get(symbol),
            weight=weight,
            beta=pos["beta"],
            volatility=volatility,
            var_95=var_95,
            expected_return=expected_return,
            correlation_to_market=corr_to_market
        )
    
    def calculate_sector_exposures(self) -> Dict[SectorType, SectorExposure]:
        """Calculate exposure by sector"""
        sector_values = defaultdict(float)
        sector_betas = defaultdict(list)
        sector_positions = defaultdict(list)
        
        for symbol, pos in self.positions.items():
            if pos["qty"] == 0:
                continue
            
            value = pos["value"]
            sector = self.sector_map.get(symbol)
            
            if sector:
                sector_values[sector] += value
                sector_betas[sector].append(pos["beta"])
                sector_positions[sector].append(symbol)
        
        exposures = {}
        for sector, notional in sector_values.items():
            weight = notional / self.portfolio_value
            avg_beta = np.mean(sector_betas[sector]) if sector_betas[sector] else 1.0
            
            # Calculate sector volatility
            sector_symbols = sector_positions[sector]
            sector_returns = []
            if len(sector_symbols) > 0 and sector_symbols[0] in self.returns_history:
                sector_returns = [
                    np.mean(list(self.returns_history.get(s, [])))
                    for s in sector_symbols
                    if s in self.returns_history
                ]
            
            volatility = np.std(sector_returns) * np.sqrt(252) if sector_returns else 0.15
            corr_to_market = 0.7  # Placeholder
            
            exposures[sector] = SectorExposure(
                sector=sector,
                notional_value=notional,
                weight=weight,
                avg_beta=avg_beta,
                volatility=volatility,
                correlation_to_market=corr_to_market
            )
        
        return exposures
    
    def calculate_portfolio_var(self) -> Tuple[float, float, float]:
        """
        Calculate portfolio VaR and CVaR
        
        Returns:
            (var_95, var_99, cvar_95)
        """
        if len(self.returns_history) == 0:
            return 0.0, 0.0, 0.0
        
        # Aggregate portfolio returns
        portfolio_returns = []
        for symbol, pos in self.positions.items():
            if pos["qty"] == 0 or symbol not in self.returns_history:
                continue
            
            weight = pos["value"] / self.portfolio_value
            symbol_returns = list(self.returns_history[symbol])
            
            for ret in symbol_returns:
                portfolio_returns.append(ret * weight)
        
        if len(portfolio_returns) < 10:
            return 0.0, 0.0, 0.0
        
        # VaR at different confidence levels
        var_95 = np.percentile(portfolio_returns, 5)
        var_99 = np.percentile(portfolio_returns, 1)
        
        # CVaR (Expected Shortfall) = average of returns worse than VaR
        cvar_95 = np.mean([r for r in portfolio_returns if r <= var_95])
        
        # Convert to dollars
        var_95_dollars = var_95 * self.portfolio_value
        var_99_dollars = var_99 * self.portfolio_value
        cvar_95_dollars = cvar_95 * self.portfolio_value
        
        return var_95_dollars, var_99_dollars, cvar_95_dollars
    
    def detect_correlation_breakdowns(self) -> List[CorrelationBreakdown]:
        """Detect unusual correlation changes"""
        breakdowns = []
        
        symbols = list(self.positions.keys())
        for i, sym1 in enumerate(symbols):
            if sym1 not in self.returns_history:
                continue
            
            for sym2 in symbols[i+1:]:
                if sym2 not in self.returns_history:
                    continue
                
                recent_corr = self._calculate_correlation(sym1, sym2)
                hist_key = (sym1, sym2)
                hist_corr = self.historical_correlations.get(hist_key, recent_corr)
                
                corr_change = abs(recent_corr - hist_corr)
                
                # Threshold for significant change
                if corr_change > 0.3:
                    severity = "high" if corr_change > 0.5 else "medium"
                    
                    breakdown = CorrelationBreakdown(
                        symbols=(sym1, sym2),
                        historical_correlation=hist_corr,
                        recent_correlation=recent_corr,
                        correlation_change=corr_change,
                        severity=severity,
                        timestamp=datetime.now()
                    )
                    breakdowns.append(breakdown)
                    self.correlation_breakdowns.append(breakdown)
                
                # Update historical
                self.historical_correlations[hist_key] = recent_corr
        
        return breakdowns
    
    def _calculate_correlation(self, sym1: str, sym2: str) -> float:
        """Calculate correlation between two symbols"""
        returns1 = np.array(list(self.returns_history.get(sym1, [])))
        returns2 = np.array(list(self.returns_history.get(sym2, [])))
        
        if len(returns1) == 0 or len(returns2) == 0:
            return 0.5
        
        # Use only overlapping periods
        min_len = min(len(returns1), len(returns2))
        returns1 = returns1[-min_len:]
        returns2 = returns2[-min_len:]
        
        if len(returns1) < 2:
            return 0.5
        
        corr = np.corrcoef(returns1, returns2)[0, 1]
        return 0.5 if np.isnan(corr) else corr
    
    def check_portfolio_alerts(self) -> List[RiskWarning]:
        """Generate portfolio risk warnings"""
        warnings = []
        
        # Check sector concentration
        sector_exposures = self.calculate_sector_exposures()
        for sector, exposure in sector_exposures.items():
            if exposure.weight > self.max_sector_weight:
                warnings.append(RiskWarning(
                    warning_type="sector_concentration",
                    severity="high",
                    message=f"{sector.value} at {exposure.weight:.1%} of portfolio",
                    recommendation=f"Reduce {sector.value} exposure",
                    timestamp=datetime.now()
                ))
        
        # Check correlation concentrations
        high_correlations = 0
        for sym1 in self.positions:
            for sym2 in self.positions:
                if sym1 < sym2:  # Avoid duplicates
                    corr = self._calculate_correlation(sym1, sym2)
                    if abs(corr) > self.max_correlation_threshold:
                        high_correlations += 1
        
        if high_correlations > 5:
            warnings.append(RiskWarning(
                warning_type="high_correlation",
                severity="medium",
                message=f"{high_correlations} highly-correlated position pairs",
                recommendation="Diversify across uncorrelated assets",
                timestamp=datetime.now()
            ))
        
        self.active_warnings = warnings
        return warnings
    
    def get_portfolio_risk_snapshot(self) -> PortfolioRiskSnapshot:
        """Get comprehensive portfolio risk snapshot"""
        var_95, var_99, cvar_95 = self.calculate_portfolio_var()
        sector_exposures = self.calculate_sector_exposures()
        warnings = self.check_portfolio_alerts()
        breakdowns = self.detect_correlation_breakdowns()
        
        # Determine overall risk level
        if len([w for w in warnings if w.severity == "critical"]) > 0:
            risk_level = RiskLevel.CRITICAL
        elif len([w for w in warnings if w.severity == "high"]) > 1:
            risk_level = RiskLevel.ELEVATED
        elif len([w for w in warnings if w.severity in ["high", "medium"]]) > 0:
            risk_level = RiskLevel.MODERATE
        else:
            risk_level = RiskLevel.LOW
        
        # Calculate exposures
        total_position_value = sum(pos["value"] for pos in self.positions.values())
        gross_exposure = sum(abs(pos["value"]) for pos in self.positions.values())
        
        # Sector diversity
        if sector_exposures:
            weights = [e.weight for e in sector_exposures.values()]
            herfindahl = sum(w**2 for w in weights)
            sector_diversity = 1 - herfindahl
        else:
            sector_diversity = 0
        
        # Correlations
        all_correlations = []
        for sym1 in self.positions:
            for sym2 in self.positions:
                if sym1 < sym2:
                    corr = self._calculate_correlation(sym1, sym2)
                    all_correlations.append(corr)
        
        avg_corr = np.mean(all_correlations) if all_correlations else 0.5
        max_corr = np.max(all_correlations) if all_correlations else 0.5
        high_corr_count = sum(1 for c in all_correlations if c > 0.8)
        
        # Greeks (placeholder - would require options data)
        portfolio_delta = sum(self.greeks.get(s, {}).get("delta", 0) for s in self.positions)
        portfolio_gamma = sum(self.greeks.get(s, {}).get("gamma", 0) for s in self.positions)
        portfolio_vega = sum(self.greeks.get(s, {}).get("vega", 0) for s in self.positions)
        portfolio_theta = sum(self.greeks.get(s, {}).get("theta", 0) for s in self.positions)
        
        # Largest sector
        largest_sector = max(sector_exposures.items(), key=lambda x: x[1].weight)[0] if sector_exposures else None
        largest_weight = sector_exposures[largest_sector].weight if largest_sector else 0
        
        return PortfolioRiskSnapshot(
            timestamp=datetime.now(),
            overall_risk_level=risk_level,
            total_portfolio_value=self.portfolio_value,
            var_95_daily=var_95,
            var_99_daily=var_99,
            cvar_95_daily=cvar_95,
            gross_exposure=gross_exposure,
            net_exposure=total_position_value,
            leverage=gross_exposure / self.portfolio_value if self.portfolio_value > 0 else 1.0,
            largest_sector=largest_sector,
            largest_sector_weight=largest_weight,
            sector_diversity=sector_diversity,
            avg_correlation=avg_corr,
            max_correlation=max_corr,
            num_high_correlations=high_corr_count,
            active_warnings=warnings,
            correlation_breakdowns=breakdowns,
            portfolio_delta=portfolio_delta,
            portfolio_gamma=portfolio_gamma,
            portfolio_vega=portfolio_vega,
            portfolio_theta=portfolio_theta
        )


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("REAL-TIME PORTFOLIO RISK AGGREGATION DEMO")
    print("=" * 70)
    print("\nFeatures:")
    print("  - Dynamic correlation tracking")
    print("  - Value-at-Risk (VaR) calculation")
    print("  - Expected Shortfall (CVaR)")
    print("  - Sector exposure monitoring")
    print("  - Correlation breakdown detection")
    print("  - Portfolio risk warnings")
    print("  - Greeks aggregation")
    print("\nSee code for detailed implementation and integration")
