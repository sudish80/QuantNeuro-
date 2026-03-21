"""
MULTI-ASSET CORRELATION MATRIX - Phase 4 Example

Demonstrates real-time cross-asset correlation computation for:
- Portfolio risk aggregation
- Asset clustering
- Diversification analysis
- Rebalancing triggers

Features:
- Rolling correlation calculation
- Correlation breakdown detection
- Correlation-based position sizing
- Dynamic rebalancing triggers

Usage:
    corr_engine = CorrelationEngine(universe=["AAPL", "GOOGL", "MSFT", "JNJ"])
    
    # Update with new prices
    corr_engine.update_prices(prices_dict)
    
    # Get correlation matrix
    corr_matrix = corr_engine.get_correlation_matrix()
    
    # Detect correlation breakdowns
    breakdown = corr_engine.detect_correlation_breakdown()
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class CorrelationMetrics:
    """Correlation analysis results."""
    correlation_matrix: np.ndarray
    avg_correlation: float
    max_correlation: float
    min_correlation: float
    correlation_std: float
    breakdown_detected: bool
    breakdown_severity: float  # 0-1, 1=major breakdown


@dataclass
class AssetCluster:
    """Cluster of correlated assets."""
    assets: List[str]
    avg_correlation: float
    size: int
    concentration: float


# ============================================================================
# CORRELATION ENGINE
# ============================================================================

class CorrelationEngine:
    """
    Compute and track multi-asset correlations.
    
    Enables:
    - Real-time correlation matrix updates
    - Breakdown detection (diversification failure)
    - Asset clustering
    - Risk aggregation
    """
    
    def __init__(
        self,
        universe: List[str],
        lookback_days: int = 60,
        update_frequency: str = "daily"
    ):
        self.universe = universe
        self.lookback_days = lookback_days
        self.update_frequency = update_frequency
        
        # Price history: {ticker: [prices]}
        self.price_history: Dict[str, List[float]] = {ticker: [] for ticker in universe}
        self.timestamps: List[datetime] = []
        
        # Correlation tracking
        self.correlation_matrix: Optional[np.ndarray] = None
        self.correlation_history: List[np.ndarray] = []
        
        # Breakdown tracking
        self.breakdown_history: List[bool] = []
        self.last_correlation_matrix: Optional[np.ndarray] = None
    
    def update_prices(
        self,
        prices: Dict[str, float],
        timestamp: Optional[datetime] = None
    ):
        """
        Update with new price data.
        
        Args:
            prices: {ticker: price}
            timestamp: Update timestamp (default: now)
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        # Record prices
        for ticker in self.universe:
            if ticker in prices:
                self.price_history[ticker].append(prices[ticker])
        
        self.timestamps.append(timestamp)
        
        # Keep only lookback window
        if len(self.timestamps) > self.lookback_days:
            removed_idx = len(self.timestamps) - self.lookback_days - 1
            for ticker in self.universe:
                self.price_history[ticker].pop(0)
            self.timestamps.pop(0)
        
        # Recalculate correlation matrix
        self._compute_correlation_matrix()
    
    def _compute_correlation_matrix(self) -> np.ndarray:
        """Compute correlation matrix from price history."""
        if any(len(self.price_history[t]) < 2 for t in self.universe):
            return None
        
        # Convert prices to returns
        returns_dict = {}
        for ticker in self.universe:
            prices = np.array(self.price_history[ticker])
            returns = np.diff(prices) / prices[:-1]
            returns_dict[ticker] = returns
        
        # Build returns matrix (assets x time)
        returns_matrix = np.array([returns_dict[t] for t in self.universe])
        
        # Compute correlation
        self.last_correlation_matrix = self.correlation_matrix
        self.correlation_matrix = np.corrcoef(returns_matrix)
        
        return self.correlation_matrix
    
    def get_correlation_matrix(self) -> Optional[np.ndarray]:
        """Get current correlation matrix."""
        return self.correlation_matrix
    
    def get_asset_correlation(self, ticker1: str, ticker2: str) -> Optional[float]:
        """Get correlation between two assets."""
        if self.correlation_matrix is None:
            return None
        
        idx1 = self.universe.index(ticker1)
        idx2 = self.universe.index(ticker2)
        
        return self.correlation_matrix[idx1, idx2]
    
    def detect_correlation_breakdown(
        self,
        threshold_change_pct: float = 0.20
    ) -> CorrelationMetrics:
        """
        Detect correlation breakdown (loss of diversification).
        
        A breakdown occurs when:
        1. Average correlation increased significantly
        2. Assets that were uncorrelated become correlated
        3. Low correlation assets move together
        
        Args:
            threshold_change_pct: Alert if correlation changes >20%
        
        Returns:
            CorrelationMetrics with breakdown flag
        """
        if self.correlation_matrix is None or self.last_correlation_matrix is None:
            return CorrelationMetrics(
                correlation_matrix=self.correlation_matrix,
                avg_correlation=0,
                max_correlation=0,
                min_correlation=0,
                correlation_std=0,
                breakdown_detected=False,
                breakdown_severity=0
            )
        
        # Current statistics
        current_corr_off_diag = self.correlation_matrix[
            np.triu_indices_from(self.correlation_matrix, k=1)
        ]
        current_avg = np.mean(current_corr_off_diag)
        current_max = np.max(current_corr_off_diag)
        current_min = np.min(current_corr_off_diag)
        current_std = np.std(current_corr_off_diag)
        
        # Previous statistics
        previous_corr_off_diag = self.last_correlation_matrix[
            np.triu_indices_from(self.last_correlation_matrix, k=1)
        ]
        previous_avg = np.mean(previous_corr_off_diag)
        
        # Detect breakdown
        correlation_change = (current_avg - previous_avg) / (abs(previous_avg) + 1e-6)
        breakdown_detected = abs(correlation_change) > threshold_change_pct
        
        # Severity: how much correlations increased
        severity = min(1.0, abs(correlation_change) / threshold_change_pct)
        
        self.breakdown_history.append(breakdown_detected)
        self.correlation_history.append(self.correlation_matrix.copy())
        
        return CorrelationMetrics(
            correlation_matrix=self.correlation_matrix,
            avg_correlation=current_avg,
            max_correlation=current_max,
            min_correlation=current_min,
            correlation_std=current_std,
            breakdown_detected=breakdown_detected,
            breakdown_severity=severity
        )
    
    def cluster_assets(
        self,
        correlation_threshold: float = 0.70
    ) -> List[AssetCluster]:
        """
        Group assets by correlation.
        
        Assets with correlation > threshold are grouped together.
        
        Args:
            correlation_threshold: Minimum correlation to cluster
        
        Returns:
            List of asset clusters
        """
        if self.correlation_matrix is None:
            return []
        
        # Union-find for clustering
        n = len(self.universe)
        parent = list(range(n))
        
        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]
        
        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py
        
        # Merge assets with correlation > threshold
        for i in range(n):
            for j in range(i + 1, n):
                if abs(self.correlation_matrix[i, j]) > correlation_threshold:
                    union(i, j)
        
        # Build clusters
        clusters_dict: Dict[int, List[int]] = {}
        for i in range(n):
            root = find(i)
            if root not in clusters_dict:
                clusters_dict[root] = []
            clusters_dict[root].append(i)
        
        # Create cluster objects
        clusters = []
        for indices in clusters_dict.values():
            cluster_tickers = [self.universe[i] for i in indices]
            
            # Average correlation within cluster
            if len(indices) > 1:
                cluster_corrs = []
                for i in range(len(indices)):
                    for j in range(i + 1, len(indices)):
                        cluster_corrs.append(
                            abs(self.correlation_matrix[indices[i], indices[j]])
                        )
                avg_corr = np.mean(cluster_corrs) if cluster_corrs else 0
            else:
                avg_corr = 1.0
            
            clusters.append(AssetCluster(
                assets=cluster_tickers,
                avg_correlation=avg_corr,
                size=len(cluster_tickers),
                concentration=sum(1 for t in cluster_tickers) / len(self.universe)
            ))
        
        return clusters
    
    def get_diversification_ratio(
        self,
        weights: Optional[Dict[str, float]] = None
    ) -> float:
        """
        Calculate portfolio diversification ratio.
        
        Ratio = weighted avg vol / portfolio vol
        Range [1, N] where 1=single asset, N=perfectly uncorrelated
        
        Args:
            weights: Portfolio weights. If None, use equal weight.
        
        Returns:
            Diversification ratio (>1.5 is well diversified)
        """
        if self.correlation_matrix is None:
            return 0
        
        # Use equal weights if not provided
        if weights is None:
            weights = {ticker: 1/len(self.universe) for ticker in self.universe}
        
        # Volatilities (diagonal of correlation matrix * assumes unit variance)
        # For now, assume unit variance, so volatility = 1 for all
        
        portfolio_vol = np.sqrt(
            sum(weights[self.universe[i]] ** 2 for i in range(len(self.universe)))
            + 2 * sum(
                weights[self.universe[i]] * weights[self.universe[j]] 
                * self.correlation_matrix[i, j]
                for i in range(len(self.universe))
                for j in range(i + 1, len(self.universe))
            )
        )
        
        # Average volatility (expected vol if equal weight)
        avg_vol = np.mean([1.0 for _ in self.universe])
        
        if portfolio_vol > 0:
            div_ratio = avg_vol / portfolio_vol
        else:
            div_ratio = 0
        
        return div_ratio
    
    def rebalance_by_cluster(
        self,
        target_allocation: float = 0.25
    ) -> Dict[str, float]:
        """
        Rebalance portfolio to spread across clusters.
        
        Allocates equally across clusters, then equally within clusters.
        
        Args:
            target_allocation: Target per-cluster allocation
        
        Returns:
            {ticker: weight} after rebalancing
        """
        clusters = self.cluster_assets()
        weights = {}
        
        per_cluster_weight = target_allocation
        
        for cluster in clusters:
            per_asset_weight = per_cluster_weight / len(cluster.assets)
            for ticker in cluster.assets:
                weights[ticker] = per_asset_weight
        
        # Normalize to sum to 1
        total = sum(weights.values())
        if total > 0:
            weights = {k: v/total for k, v in weights.items()}
        
        return weights


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

def example_multi_asset_correlation():
    """Demonstrate multi-asset correlation matrix usage."""
    print("Multi-Asset Correlation Matrix Example")
    print("=" * 70)
    
    # Create engine for 5 tech stocks
    universe = ["AAPL", "GOOGL", "MSFT", "META", "NVDA"]
    engine = CorrelationEngine(universe=universe, lookback_days=60)
    
    print(f"\nUniverse: {universe}")
    print("Simulating 30 days of price data...\n")
    
    # Simulate 30 days of prices
    np.random.seed(42)
    prices = {ticker: 100 for ticker in universe}
    
    for day in range(30):
        # Random walk for all assets
        for ticker in universe:
            daily_return = np.random.normal(0.0005, 0.02)
            prices[ticker] *= (1 + daily_return)
        
        engine.update_prices(
            prices=prices,
            timestamp=datetime.utcnow() - timedelta(days=30-day)
        )
    
    # Get correlation matrix
    corr_matrix = engine.get_correlation_matrix()
    
    print("Correlation Matrix:")
    print("-" * 70)
    df_corr = pd.DataFrame(
        corr_matrix,
        index=universe,
        columns=universe
    )
    print(df_corr.round(3))
    
    # Analyze correlations
    metrics = engine.detect_correlation_breakdown()
    print(f"\nCorrelation Statistics:")
    print(f"  Average correlation: {metrics.avg_correlation:.3f}")
    print(f"  Max correlation: {metrics.max_correlation:.3f}")
    print(f"  Min correlation: {metrics.min_correlation:.3f}")
    print(f"  Std dev: {metrics.correlation_std:.3f}")
    print(f"  Breakdown detected: {metrics.breakdown_detected}")
    
    # Asset clustering
    clusters = engine.cluster_assets(correlation_threshold=0.70)
    print(f"\nAsset Clusters (correlation > 0.70):")
    for i, cluster in enumerate(clusters):
        print(f"  Cluster {i+1}: {cluster.assets}")
        print(f"    Avg correlation: {cluster.avg_correlation:.3f}")
    
    # Diversification ratio
    div_ratio = engine.get_diversification_ratio()
    print(f"\nDiversification Ratio: {div_ratio:.2f}")
    print("  (>1.5 = well diversified)")
    
    # Cluster-based rebalancing
    new_weights = engine.rebalance_by_cluster(target_allocation=0.25)
    print(f"\nCluster-Based Rebalancing Weights:")
    for ticker, weight in new_weights.items():
        print(f"  {ticker}: {weight:.1%}")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    example_multi_asset_correlation()
