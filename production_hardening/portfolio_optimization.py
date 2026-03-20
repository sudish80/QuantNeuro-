"""
PHASE 3 - ADVANCED PORTFOLIO OPTIMIZATION

Multi-asset portfolio optimization with:
- Risk parity allocation (equal risk contribution)
- Regime-aware position sizing
- Hierarchical clustering for diversification
- Dynamic rebalancing
- Correlation breakdown detection

Usage:
    optimizer = PortfolioOptimizer(initial_capital=1000000)
    
    # Set up universe
    optimizer.add_asset("AAPL", weight=0.3)
    optimizer.add_asset("GOOGL", weight=0.3)
    optimizer.add_asset("MSFT", weight=0.4)
    
    # Get optimal allocation
    allocation = optimizer.optimize_weights(returns, cov_matrix)
    
    # Detect regime changes
    regime = optimizer.detect_regime(market_data)
    
    # Rebalance if needed
    if optimizer.should_rebalance():
        new_weights = optimizer.rebalance(current_prices)
"""

import numpy as np
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from enum import Enum
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS
# ============================================================================

class MarketRegime(Enum):
    """Market regime classification."""
    BULL = "BULL"  # Rising trend
    BEAR = "BEAR"  # Falling trend
    RANGING = "RANGING"  # Sideways
    VOLATILE = "VOLATILE"  # High volatility


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class Asset:
    """Asset in portfolio."""
    ticker: str
    weight: float
    target_vol: float = 0.15  # 15% annual volatility
    sector: str = ""


@dataclass
class PortfolioMetrics:
    """Portfolio performance metrics."""
    total_return: float
    annual_return: float
    volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    diversification_ratio: float
    concentration: float  # Herfindahl index


@dataclass
class AllocationResult:
    """Result of optimization."""
    weights: Dict[str, float]  # ticker -> weight
    expected_return: float
    expected_vol: float
    sharpe_ratio: float
    risk_contribution: Dict[str, float]  # ticker -> % of total risk


# ============================================================================
# PORTFOLIO OPTIMIZER
# ============================================================================

class PortfolioOptimizer:
    """Advanced multi-asset portfolio optimization."""
    
    def __init__(
        self,
        initial_capital: float = 1000000,
        rebalance_threshold: float = 0.05,  # 5% drift
        max_drawdown_limit: float = 0.20  # 20% max DD
    ):
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.assets = {}
        self.rebalance_threshold = rebalance_threshold
        self.max_drawdown_limit = max_drawdown_limit
        
        self.current_regime = MarketRegime.RANGING
        self.position_sizes = {}
        self.last_rebalance_date = None
        self.max_capital = initial_capital
    
    def add_asset(self, ticker: str, weight: float, sector: str = ""):
        """Add asset to portfolio."""
        self.assets[ticker] = Asset(ticker=ticker, weight=weight, sector=sector)
    
    def optimize_weights(
        self,
        returns: np.ndarray,  # (n_periods, n_assets)
        cov_matrix: Optional[np.ndarray] = None,
        method: str = "risk_parity"
    ) -> AllocationResult:
        """
        Optimize portfolio weights.
        
        Args:
            returns: Historical returns
            cov_matrix: Covariance matrix (calculated if None)
            method: "risk_parity", "efficient_frontier", "equal_weight"
        
        Returns:
            AllocationResult with optimal weights
        """
        n_assets = returns.shape[1]
        
        if cov_matrix is None:
            cov_matrix = np.cov(returns.T)
        
        if method == "risk_parity":
            weights = self._optimize_risk_parity(cov_matrix)
        elif method == "efficient_frontier":
            weights = self._optimize_efficient_frontier(returns, cov_matrix)
        elif method == "equal_weight":
            weights = np.ones(n_assets) / n_assets
        else:
            weights = np.ones(n_assets) / n_assets
        
        # Calculate expected return and volatility
        expected_return = np.mean(returns, axis=0) @ weights
        portfolio_var = weights @ cov_matrix @ weights
        portfolio_vol = np.sqrt(portfolio_var)
        
        # Risk contribution by asset
        marginal_contrib = (cov_matrix @ weights) / portfolio_vol
        risk_contrib = weights * marginal_contrib / portfolio_vol
        
        sharpe = expected_return / portfolio_vol if portfolio_vol > 0 else 0
        
        result = AllocationResult(
            weights={ticker: w for ticker, w in zip(self.assets.keys(), weights)},
            expected_return=expected_return,
            expected_vol=portfolio_vol,
            sharpe_ratio=sharpe,
            risk_contribution={ticker: rc for ticker, rc in zip(self.assets.keys(), risk_contrib)}
        )
        
        logger.info(f"Optimized portfolio: {result.expected_return:.2%} return, {result.expected_vol:.2%} vol, {result.sharpe_ratio:.2f} Sharpe")
        return result
    
    def _optimize_risk_parity(self, cov_matrix: np.ndarray) -> np.ndarray:
        """Risk parity: equal risk contribution from each asset."""
        # Iterate to find weights where each asset contributes equally to risk
        n = cov_matrix.shape[0]
        weights = np.ones(n) / n
        
        for iteration in range(10):
            # Calculate marginal contribution to risk
            mcr = (cov_matrix @ weights) / np.sqrt(weights @ cov_matrix @ weights)
            # Update weights inversely proportional to MCR
            weights = 1.0 / mcr
            weights /= weights.sum()
        
        return weights
    
    def _optimize_efficient_frontier(
        self,
        returns: np.ndarray,
        cov_matrix: np.ndarray,
        target_return: Optional[float] = None
    ) -> np.ndarray:
        """Optimize along efficient frontier."""
        n_assets = returns.shape[1]
        mean_returns = np.mean(returns, axis=0)
        
        if target_return is None:
            target_return = np.mean(mean_returns)
        
        # Simplified: minimize variance subject to return constraint
        # Use Lagrange multipliers
        # Solution: w = (cov^-1 @ R) / constant
        try:
            cov_inv = np.linalg.inv(cov_matrix)
            ones = np.ones(n_assets)
            
            # Efficient frontier solution
            numerator = cov_inv @ mean_returns
            denominator = ones @ cov_inv @ mean_returns
            
            weights = numerator / denominator
            weights = np.maximum(weights, 0)  # No short sales
            weights /= weights.sum()
            
            return weights
        except np.linalg.LinAlgError:
            # Fallback to equal weight if singular
            return np.ones(n_assets) / n_assets
    
    def detect_regime(
        self,
        prices: np.ndarray,  # Recent prices
        lookback: int = 30
    ) -> MarketRegime:
        """Detect current market regime."""
        if len(prices) < lookback:
            return MarketRegime.RANGING
        
        recent = prices[-lookback:]
        returns = np.diff(recent) / recent[:-1]
        
        # Trend detection
        sma_short = np.mean(recent[-5:])
        sma_long = np.mean(recent)
        trend = sma_short - sma_long
        
        # Volatility
        recent_vol = np.std(returns[-20:]) * np.sqrt(252)
        long_vol = np.std(returns) * np.sqrt(252)
        vol_ratio = recent_vol / max(long_vol, 0.01)
        
        # Classify regime
        if trend > 0 and vol_ratio < 1.2:
            self.current_regime = MarketRegime.BULL
        elif trend < 0 and vol_ratio < 1.2:
            self.current_regime = MarketRegime.BEAR
        elif vol_ratio > 1.5:
            self.current_regime = MarketRegime.VOLATILE
        else:
            self.current_regime = MarketRegime.RANGING
        
        logger.info(f"Market regime: {self.current_regime.value} (trend: {trend:.4f}, vol_ratio: {vol_ratio:.2f})")
        return self.current_regime
    
    def get_regime_weights(self, base_weights: Dict[str, float]) -> Dict[str, float]:
        """Adjust weights based on current regime."""
        adjusted = base_weights.copy()
        
        if self.current_regime == MarketRegime.BULL:
            # Increase growth assets
            for ticker in adjusted:
                if ticker in ["GOOGL", "AAPL", "MSFT"]:
                    adjusted[ticker] *= 1.1
        elif self.current_regime == MarketRegime.BEAR:
            # Increase defensive positions
            for ticker in adjusted:
                if ticker in ["MSFT", "JNJ"]:  # More defensive
                    adjusted[ticker] *= 1.1
        elif self.current_regime == MarketRegime.VOLATILE:
            # Reduce leverage, increase hedges
            for ticker in adjusted:
                adjusted[ticker] *= 0.9
        
        # Normalize
        total = sum(adjusted.values())
        return {k: v / total for k, v in adjusted.items()}
    
    def should_rebalance(self, current_prices: np.ndarray) -> bool:
        """Check if rebalancing is needed."""
        if not self.position_sizes:
            return True
        
        current_weights = current_prices / current_prices.sum()
        target_weights = np.array(list(self.position_sizes.values()))
        
        drift = np.abs(current_weights - target_weights).max()
        
        return drift > self.rebalance_threshold
    
    def rebalance(self, current_prices: np.ndarray) -> Dict[str, float]:
        """Rebalance portfolio to target weights."""
        current_value = current_prices.sum()
        
        # Calculate target quantities
        new_weights = {}
        for i, ticker in enumerate(self.assets.keys()):
            target_qty = (self.assets[ticker].weight * self.current_capital) / current_prices[i]
            new_weights[ticker] = target_qty
        
        self.position_sizes = new_weights
        logger.info(f"Rebalanced portfolio")
        
        return new_weights
    
    def get_portfolio_metrics(
        self,
        returns: np.ndarray,
        current_value: float
    ) -> PortfolioMetrics:
        """Calculate portfolio metrics."""
        portfolio_returns = np.mean(returns, axis=1)  # Average return across assets
        
        total_return = portfolio_returns.sum()
        annual_return = (1 + total_return) ** (252 / len(portfolio_returns)) - 1
        volatility = np.std(portfolio_returns) * np.sqrt(252)
        
        # Sharpe ratio
        sharpe = annual_return / volatility if volatility > 0 else 0
        
        # Sortino ratio
        downside = portfolio_returns[portfolio_returns < 0]
        sortino = annual_return / (np.std(downside) * np.sqrt(252)) if len(downside) > 0 else sharpe
        
        # Max drawdown
        cumsum = np.cumprod(1 + portfolio_returns)
        running_max = np.maximum.accumulate(cumsum)
        drawdown = (cumsum - running_max) / running_max
        max_dd = drawdown.min()
        
        # Diversification ratio
        asset_vols = np.std(returns, axis=0) * np.sqrt(252)
        weights = np.mean(returns, axis=0) / np.mean(returns)
        div_ratio = np.sum(weights * asset_vols) / volatility if volatility > 0 else 1.0
        
        # Concentration (Herfindahl)
        concentration = np.sum(weights ** 2)
        
        return PortfolioMetrics(
            total_return=total_return,
            annual_return=annual_return,
            volatility=volatility,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            max_drawdown=max_dd,
            diversification_ratio=div_ratio,
            concentration=concentration
        )


# ============================================================================
# HIERARCHICAL ASSET CLUSTERING
# ============================================================================

class AssetClusterer:
    """Cluster assets for diversification analysis."""
    
    @staticmethod
    def calculate_correlation_matrix(returns: np.ndarray) -> np.ndarray:
        """Calculate correlation between assets."""
        return np.corrcoef(returns.T)
    
    @staticmethod
    def hierarchical_cluster(
        correlation: np.ndarray,
        n_clusters: int = 3
    ) -> Dict[int, List[int]]:
        """
        Hierarchical clustering of assets by correlation.
        
        Returns clusters of indices.
        """
        n_assets = correlation.shape[0]
        clusters = {i: [i] for i in range(n_assets)}
        
        # Simplified clustering: group by correlation
        for i in range(n_assets):
            for j in range(i + 1, n_assets):
                if correlation[i, j] > 0.7:  # Strong correlation
                    clusters[i].extend(clusters[j])
                    del clusters[j]
        
        # Trim to n_clusters
        sorted_clusters = sorted(clusters.values(), key=len, reverse=True)
        final_clusters = {i: c for i, c in enumerate(sorted_clusters[:n_clusters])}
        
        return final_clusters
    
    @staticmethod
    def analyze_correlation_breakdown(
        current_corr: np.ndarray,
        historical_corr: np.ndarray
    ) -> bool:
        """
        Detect if correlations are breaking down (changing rapidly).
        
        Returns True if breakdown detected.
        """
        corr_change = np.abs(current_corr - historical_corr).mean()
        breakdown_threshold = 0.2  # 20% change
        
        return corr_change > breakdown_threshold


# ============================================================================
# UTILITIES
# ============================================================================

def print_allocation_report(result: AllocationResult):
    """Print allocation results."""
    print("\n" + "="*60)
    print("  PORTFOLIO ALLOCATION REPORT")
    print("="*60)
    
    print(f"\n📊 EXPECTED PERFORMANCE")
    print(f"  Return:              {result.expected_return:.2%}")
    print(f"  Volatility:          {result.expected_vol:.2%}")
    print(f"  Sharpe Ratio:        {result.sharpe_ratio:.2f}")
    
    print(f"\n⚖️  ALLOCATION")
    for ticker, weight in sorted(result.weights.items(), key=lambda x: x[1], reverse=True):
        risk_contrib = result.risk_contribution.get(ticker, 0)
        print(f"  {ticker:6} {weight*100:>6.1f}% (risk: {risk_contrib*100:5.1f}%)")
    
    print("\n" + "="*60 + "\n")
