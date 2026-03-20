"""
PHASE 3 - REAL-TIME FEATURE PIPELINE

Streaming feature computation for online/offline consistency:
- Real-time feature extraction (market data, trades, signals)
- Online/offline aggregation consistency
- Feature versioning with timestamps
- Low-latency serving (<50ms)
- Batch feature computation for backfilling

Usage:
    pipeline = RealTimeFeaturePipeline()
    
    # Register features
    pipeline.register_feature(
        name="sma_20",
        computation_fn=lambda prices: prices[-20:].mean(),
        sources=["market_prices"],
        update_frequency_sec=60
    )
    
    # Stream online features
    features = pipeline.compute_online_features(
        ticker="AAPL",
        timestamp=datetime.now()
    )
    
    # Batch offline features (for training)
    batch_features = pipeline.compute_offline_features(
        tickers=["AAPL", "GOOGL"],
        date_range=(start_date, end_date)
    )
"""

import numpy as np
from dataclasses import dataclass, field
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Callable, Any
from enum import Enum
import logging
from collections import deque

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS
# ============================================================================

class ComputationMode(Enum):
    """Feature computation mode."""
    ONLINE = "ONLINE"  # Real-time, low-latency
    OFFLINE = "OFFLINE"  # Batch, high accuracy


class FeatureStatus(Enum):
    """Feature computation status."""
    FRESH = "FRESH"  # Recently computed (<5m)
    STALE = "STALE"  # Older computation (5m-1h)
    MISSING = "MISSING"  # Not computed


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class Feature:
    """Feature definition."""
    name: str
    sources: List[str]  # Data sources
    update_frequency_sec: int
    aggregation_window_sec: int = 3600  # 1 hour
    computation_fn: Optional[Callable] = None
    version: str = "v1"


@dataclass
class FeatureValue:
    """Computed feature value."""
    feature_name: str
    ticker: str
    timestamp: datetime
    value: float
    mode: ComputationMode
    status: FeatureStatus
    computation_time_ms: float


@dataclass
class FeatureGroup:
    """Group of related features."""
    features: Dict[str, float]  # feature_name -> value
    timestamp: datetime
    consistency_score: float = 1.0  # 0-1, 1=perfect consistency


# ============================================================================
# REAL-TIME FEATURE PIPELINE
# ============================================================================

class RealTimeFeaturePipeline:
    """Stream features with online/offline consistency."""
    
    def __init__(self):
        self.features = {}  # name -> Feature
        self.feature_cache = {}  # (ticker, feature_name) -> FeatureValue
        self.online_cache = {}  # (ticker, feature_name, timestamp) -> float
        self.offline_cache = {}  # (ticker, feature_name, date) -> float
        
        self.data_streams = {}  # ticker -> deque of (timestamp, price, volume)
        self.max_history = 300  # Keep 5 minutes at 1-second resolution
    
    def register_feature(
        self,
        name: str,
        computation_fn: Callable,
        sources: List[str],
        update_frequency_sec: int = 60,
        aggregation_window_sec: int = 3600
    ):
        """Register feature computation."""
        feature = Feature(
            name=name,
            sources=sources,
            update_frequency_sec=update_frequency_sec,
            aggregation_window_sec=aggregation_window_sec,
            computation_fn=computation_fn
        )
        
        self.features[name] = feature
        logger.info(f"Registered feature: {name}")
    
    # ========== ONLINE FEATURES (Real-time) ==========
    
    def ingest_market_data(
        self,
        ticker: str,
        timestamp: datetime,
        price: float,
        volume: int
    ):
        """Ingest real-time market data."""
        if ticker not in self.data_streams:
            self.data_streams[ticker] = deque(maxlen=self.max_history)
        
        self.data_streams[ticker].append((timestamp, price, volume))
    
    def compute_online_features(
        self,
        ticker: str,
        timestamp: datetime,
        feature_names: Optional[List[str]] = None
    ) -> FeatureGroup:
        """
        Compute features in real-time.
        
        Low-latency computation using recent data.
        """
        if feature_names is None:
            feature_names = list(self.features.keys())
        
        features = {}
        start = datetime.now()
        
        if ticker not in self.data_streams:
            logger.warning(f"No data for {ticker}")
            return FeatureGroup(features={}, timestamp=timestamp, consistency_score=0)
        
        data = list(self.data_streams[ticker])
        prices = np.array([price for _, price, _ in data])
        
        for feature_name in feature_names:
            if feature_name not in self.features:
                continue
            
            feature = self.features[feature_name]
            
            try:
                # Use pre-computed function
                if feature.computation_fn:
                    value = feature.computation_fn(prices)
                else:
                    value = self._compute_standard_feature(feature_name, prices)
                
                cache_key = (ticker, feature_name, timestamp)
                self.online_cache[cache_key] = value
                features[feature_name] = value
                
            except Exception as e:
                logger.error(f"Error computing {feature_name}: {e}")
                features[feature_name] = np.nan
        
        computation_time = (datetime.now() - start).total_seconds() * 1000
        
        return FeatureGroup(
            features=features,
            timestamp=timestamp,
            consistency_score=self._calculate_consistency(ticker, timestamp)
        )
    
    # ========== OFFLINE FEATURES (Batch) ==========
    
    def compute_offline_features(
        self,
        tickers: List[str],
        date_range: Tuple[date, date],
        feature_names: Optional[List[str]] = None,
        batch_size: int = 100
    ) -> Dict[str, np.ndarray]:
        """
        Compute features in batch (for training).
        
        Higher accuracy, higher latency.
        """
        if feature_names is None:
            feature_names = list(self.features.keys())
        
        all_features = {}
        
        for ticker in tickers:
            features = {}
            start_date, end_date = date_range
            
            # Simulate fetching historical data
            current_date = start_date
            while current_date <= end_date:
                # Get historical prices (would be from database)
                prices = self._fetch_historical_prices(ticker, current_date, lookback=300)
                
                if prices is None:
                    current_date += timedelta(days=1)
                    continue
                
                for feature_name in feature_names:
                    if feature_name not in self.features:
                        continue
                    
                    feature = self.features[feature_name]
                    
                    try:
                        if feature.computation_fn:
                            value = feature.computation_fn(prices)
                        else:
                            value = self._compute_standard_feature(feature_name, prices)
                        
                        cache_key = (ticker, feature_name, current_date)
                        self.offline_cache[cache_key] = value
                        
                        if feature_name not in features:
                            features[feature_name] = []
                        features[feature_name].append(value)
                    
                    except Exception as e:
                        logger.error(f"Error computing {feature_name} offline: {e}")
                
                current_date += timedelta(days=1)
            
            all_features[ticker] = features
        
        logger.info(f"Computed offline features for {len(tickers)} tickers, {len(all_features)} dates")
        return all_features
    
    # ========== CONSISTENCY CHECKS ==========
    
    def check_online_offline_consistency(
        self,
        ticker: str,
        feature_name: str,
        date_: date
    ) -> float:
        """
        Verify online and offline computations match.
        
        Returns consistency score (0-1, 1=perfect match).
        """
        # Get online value (recent cache)
        online_key = (ticker, feature_name, datetime.combine(date_, datetime.min.time()))
        online_value = self.online_cache.get(online_key)
        
        # Get offline value (batch computation)
        offline_key = (ticker, feature_name, date_)
        offline_value = self.offline_cache.get(offline_key)
        
        if online_value is None or offline_value is None:
            return 0.0
        
        # Calculate consistency (in percentage)
        if abs(offline_value) < 1e-10:
            return 1.0 if abs(online_value) < 1e-10 else 0.0
        
        pct_diff = abs(online_value - offline_value) / abs(offline_value)
        consistency = max(0, 1.0 - pct_diff)
        
        return consistency
    
    def _calculate_consistency(self, ticker: str, timestamp: datetime) -> float:
        """Calculate overall feature consistency."""
        if ticker not in self.data_streams:
            return 0.0
        
        # Simplified: check if recent data looks reasonable
        prices = np.array([p for _, p, _ in self.data_streams[ticker]])
        
        if len(prices) < 2:
            return 0.0
        
        # Check for gaps or outliers
        returns = np.diff(prices) / prices[:-1]
        extreme_moves = np.sum(np.abs(returns) > 0.05)  # > 5% moves
        
        if extreme_moves > len(returns) * 0.1:
            return 0.5  # Suspicious
        
        return 1.0  # Consistent
    
    # ========== STANDARD FEATURES ==========
    
    def _compute_standard_feature(self, feature_name: str, prices: np.ndarray) -> float:
        """Compute standard technical indicators."""
        if len(prices) < 2:
            return np.nan
        
        if feature_name == "sma_20":
            if len(prices) < 20:
                return np.nan
            return np.mean(prices[-20:])
        
        elif feature_name == "sma_50":
            if len(prices) < 50:
                return np.nan
            return np.mean(prices[-50:])
        
        elif feature_name == "rsi":
            if len(prices) < 14:
                return np.nan
            deltas = np.diff(prices[-14:])
            gains = np.mean(deltas[deltas > 0])
            losses = np.mean(np.abs(deltas[deltas < 0]))
            if losses == 0:
                return 100.0 if gains > 0 else 50.0
            rs = gains / losses
            return 100.0 - (100.0 / (1.0 + rs))
        
        elif feature_name == "macd":
            ema_12 = self._ema(prices[-26:], 12) if len(prices) >= 26 else np.nan
            ema_26 = self._ema(prices[-26:], 26) if len(prices) >= 26 else np.nan
            return ema_12 - ema_26 if not np.isnan(ema_12) else np.nan
        
        elif feature_name == "atr":
            if len(prices) < 14:
                return np.nan
            # Simplified ATR: std of returns * price
            returns = np.diff(prices[-14:]) / prices[-14:-1]
            return np.std(returns) * prices[-1]
        
        else:
            return np.nan
    
    def _ema(self, prices: np.ndarray, period: int) -> float:
        """Calculate exponential moving average."""
        if len(prices) < period:
            return np.nan
        
        multiplier = 2.0 / (period + 1.0)
        ema = prices[0]
        
        for price in prices[1:]:
            ema = price * multiplier + ema * (1.0 - multiplier)
        
        return ema
    
    def _fetch_historical_prices(
        self,
        ticker: str,
        date_: date,
        lookback: int = 300
    ) -> Optional[np.ndarray]:
        """Fetch historical prices (stub)."""
        # In production: fetch from database
        # For now: simulate with random walk
        start_price = 100.0
        returns = np.random.normal(0.0005, 0.02, lookback)
        prices = start_price * np.cumprod(1 + returns)
        
        return prices


# ============================================================================
# FEATURE CONSISTENCY MONITOR
# ============================================================================

class FeatureConsistencyMonitor:
    """Monitor online/offline feature consistency."""
    
    def __init__(self, pipeline: RealTimeFeaturePipeline):
        self.pipeline = pipeline
        self.consistency_scores = {}  # (ticker, feature) -> [scores]
        self.consistency_threshold = 0.95  # Alert if < 95%
    
    def check_all_features(
        self,
        tickers: List[str],
        date_: date
    ) -> Dict[str, float]:
        """Check consistency for all features."""
        results = {}
        
        for ticker in tickers:
            for feature_name in self.pipeline.features.keys():
                consistency = self.pipeline.check_online_offline_consistency(
                    ticker, feature_name, date_
                )
                
                key = (ticker, feature_name)
                if key not in self.consistency_scores:
                    self.consistency_scores[key] = deque(maxlen=30)  # Last 30 days
                
                self.consistency_scores[key].append(consistency)
                results[f"{ticker}_{feature_name}"] = consistency
                
                if consistency < self.consistency_threshold:
                    logger.warning(f"Low consistency: {ticker} {feature_name} = {consistency:.2%}")
        
        return results
    
    def get_consistency_report(self) -> Dict[str, float]:
        """Get summary report."""
        return {
            k: np.mean(v) for k, v in self.consistency_scores.items()
        }


# ============================================================================
# UTILITIES
# ============================================================================

def create_standard_feature_pipeline() -> RealTimeFeaturePipeline:
    """Create pre-configured feature pipeline."""
    pipeline = RealTimeFeaturePipeline()
    
    # Register standard features
    pipeline.register_feature(
        name="sma_20",
        computation_fn=lambda prices: np.mean(prices[-20:]) if len(prices) >= 20 else np.nan,
        sources=["market_prices"],
        update_frequency_sec=60
    )
    
    pipeline.register_feature(
        name="rsi",
        computation_fn=None,  # Using _compute_standard_feature
        sources=["market_prices"],
        update_frequency_sec=300
    )
    
    pipeline.register_feature(
        name="macd",
        computation_fn=None,
        sources=["market_prices"],
        update_frequency_sec=300
    )
    
    return pipeline
