"""
Vector Database Integration for Trading System

This module integrates the vector database with the existing trading pipeline for:
1. Price pattern similarity matching
2. Model prediction embedding storage
3. Trade pattern recognition
4. Drift detection
5. Regime detection

Usage:
    from production_hardening.vector_db_integration import VectorDBManager
    
    manager = VectorDBManager()
    manager.initialize()
    
    # Store patterns
    manager.store_price_pattern(prices, indicators, metadata)
    
    # Find similar patterns
    similar = manager.find_similar_patterns(prices, k=5)
    
    # Check for drift
    is_drift, similarity = manager.check_prediction_drift(prediction)
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

# Import vector database components
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from vector_database_design import (
    VectorDatabase,
    VectorDBConfig,
    VectorEntry,
    SearchFilter,
    CollectionConfig,
    CollectionStatus,
    IndexType,
    MetricType,
    create_vector_database
)


# ============================================================================
# Configuration
# ============================================================================

@dataclass
class VectorDBManagerConfig:
    """Configuration for vector DB manager."""
    # Storage
    persist_path: str = "./output/vector_db"
    enable_persistence: bool = True
    
    # Dimensions (can be different per collection)
    pattern_dimension: int = 128
    prediction_dimension: int = 64
    trade_dimension: int = 32
    feature_dimension: int = 16
    
    # Collections
    patterns_collection: str = "price_patterns"
    predictions_collection: str = "model_predictions"
    trades_collection: str = "trade_patterns"
    features_collection: str = "market_features"
    
    # Retention (days)
    pattern_retention_days: int = 180
    prediction_retention_days: int = 30
    trade_retention_days: int = 365
    feature_retention_days: int = 90
    
    # Search
    default_k: int = 5
    similarity_threshold: float = 0.85
    
    # Drift detection
    drift_threshold: float = 0.7  # Below this = significant drift
    reference_window_size: int = 100
    
    # Auto-save
    auto_save_interval: int = 100  # Save every N operations


# ============================================================================
# Vector DB Manager
# ============================================================================

class VectorDBManager:
    """
    Manages vector database operations for the trading system.
    
    Provides high-level APIs for:
    - Storing and retrieving price patterns
    - Model prediction tracking
    - Trade pattern analysis
    - Drift detection
    """
    
    def __init__(self, config: VectorDBManagerConfig | None = None):
        self.config = config or VectorDBManagerConfig()
        self.db: VectorDatabase | None = None
        self._operation_count = 0
        
        # Initialize collections
        self._collections_initialized = False
    
    def initialize(self) -> None:
        """Initialize vector database and collections."""
        if self._collections_initialized:
            return
        
        # Create database config
        db_config = VectorDBConfig(
            backend="memory",  # Use "faiss" for production
            dimension=self.config.pattern_dimension,
            persist_path=self.config.persist_path,
            enable_compression=True
        )
        
        # Create database
        self.db = create_vector_database(db_config)
        
        # Create collections for different use cases
        self.db.create_collection(
            self.config.patterns_collection,
            dimension=self.config.pattern_dimension,
            description="Historical price patterns for similarity matching",
            retention_days=self.config.pattern_retention_days
        )
        
        self.db.create_collection(
            self.config.predictions_collection,
            dimension=self.config.prediction_dimension,
            description="Model predictions for drift detection",
            retention_days=self.config.prediction_retention_days
        )
        
        self.db.create_collection(
            self.config.trades_collection,
            dimension=self.config.trade_dimension,
            description="Trade patterns for analysis",
            retention_days=self.config.trade_retention_days
        )
        
        self.db.create_collection(
            self.config.features_collection,
            dimension=self.config.feature_dimension,
            description="Market feature embeddings",
            retention_days=self.config.feature_retention_days
        )
        
        self._collections_initialized = True
        
        # Try to load existing data
        if self.config.enable_persistence:
            self._load()
    
    def _save(self) -> None:
        """Save database to disk."""
        if self.db and self.config.enable_persistence:
            self.db.save()
    
    def _load(self) -> None:
        """Load database from disk."""
        if self.db and self.config.enable_persistence:
            self.db.load()
    
    def _maybe_save(self) -> None:
        """Auto-save based on operation count."""
        self._operation_count += 1
        if self._operation_count % self.config.auto_save_interval == 0:
            self._save()
    
    # =========================================================================
    # Price Pattern Operations
    # =========================================================================
    
    def _create_pattern_embedding(
        self,
        prices: np.ndarray,
        indicators: dict | None = None,
        dimension: int = 128
    ) -> np.ndarray:
        """Create embedding from price pattern."""
        if len(prices) < 2:
            return np.zeros(dimension, dtype=np.float32)
        
        # Normalize prices
        normalized = (prices - prices.mean()) / (prices.std() + 1e-8)
        
        features = []
        
        # Return statistics
        returns = np.diff(prices) / (prices[:-1] + 1e-8)
        features.extend([
            np.mean(returns),
            np.std(returns),
            np.min(returns),
            np.max(returns),
            np.percentile(returns, 25),
            np.percentile(returns, 75),
        ])
        
        # Trend features
        features.extend([
            normalized[-1] - normalized[0],
            normalized[-1] - normalized[-5] if len(normalized) > 5 else 0,
            normalized[-5] - normalized[-10] if len(normalized) > 10 else 0,
        ])
        
        # Volatility
        if len(returns) > 5:
            rolling_vol = np.array([np.std(returns[max(0,i-5):i+1]) for i in range(5, len(returns))])
            features.extend([np.mean(rolling_vol), np.max(rolling_vol)])
        else:
            features.extend([0.0, 0.0])
        
        # Technical indicators
        if indicators:
            for key in ["RSI_14", "MACD", "ATR_14", "Volatility", "BB_width"]:
                if indicators.get(key) is not None and not np.isnan(indicators[key]):
                    features.append(float(indicators[key]))
                else:
                    features.append(0.0)
        
        # Pattern detection
        if len(prices) > 3:
            diff = np.diff(prices)
            up_moves = np.sum(diff > 0)
            down_moves = np.sum(diff < 0)
            features.extend([
                up_moves / len(diff),
                down_moves / len(diff),
                max(prices) - min(prices),  # Range
            ])
        else:
            features.extend([0.0, 0.0, 0.0])
        
        # Pad or truncate
        if len(features) < dimension:
            features.extend([0.0] * (dimension - len(features)))
        elif len(features) > dimension:
            features = features[:dimension]
        
        embedding = np.array(features[:dimension], dtype=np.float32)
        
        # Normalize
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        
        return embedding
    
    def store_price_pattern(
        self,
        prices: np.ndarray,
        indicators: dict | None = None,
        metadata: dict | None = None,
        tags: list[str] | None = None
    ) -> str:
        """
        Store a price pattern in the database.
        
        Args:
            prices: Array of historical prices
            indicators: Technical indicators
            metadata: Additional metadata (asset, timeframe, etc.)
            tags: Tags for filtering
        
        Returns:
            Pattern ID
        """
        if not self._collections_initialized:
            self.initialize()
        
        # Create embedding
        embedding = self._create_pattern_embedding(
            prices, indicators, self.config.pattern_dimension
        )
        
        # Create entry
        timestamp = datetime.now()
        pattern_id = f"pattern_{timestamp.strftime('%Y%m%d_%H%M%S')}"
        
        entry = VectorEntry(
            id=pattern_id,
            vector=embedding,
            metadata=metadata or {},
            timestamp=timestamp,
            collection=self.config.patterns_collection,
            tags=tags or []
        )
        
        # Store
        self.db.add(entry, self.config.patterns_collection)
        self._maybe_save()
        
        return pattern_id
    
    def find_similar_patterns(
        self,
        prices: np.ndarray,
        indicators: dict | None = None,
        k: int | None = None,
        filter_metadata: dict | None = None
    ) -> list[dict]:
        """
        Find similar historical patterns.
        
        Args:
            prices: Current price series
            indicators: Current indicators
            k: Number of results
            filter_metadata: Filter by metadata
        
        Returns:
            List of similar patterns with metadata and similarity score
        """
        if not self._collections_initialized:
            self.initialize()
        
        k = k or self.config.default_k
        
        # Create query embedding
        query = self._create_pattern_embedding(
            prices, indicators, self.config.pattern_dimension
        )
        
        # Create filter
        search_filter = None
        if filter_metadata:
            search_filter = SearchFilter(metadata=filter_metadata)
        
        # Search
        results = self.db.search(
            query,
            k=k,
            collection=self.config.patterns_collection,
            filter=search_filter
        )
        
        # Format results
        similar = []
        for r in results:
            similar.append({
                "id": r.entry.id,
                "similarity": r.score,
                "distance": r.distance,
                "timestamp": r.entry.timestamp.isoformat(),
                "metadata": r.entry.metadata,
                "tags": r.entry.tags
            })
        
        return similar
    
    def get_pattern_by_id(self, pattern_id: str) -> dict | None:
        """Get a pattern by ID."""
        if not self._collections_initialized:
            self.initialize()
        
        entry = self.db.get(pattern_id, self.config.patterns_collection)
        if entry:
            return {
                "id": entry.id,
                "timestamp": entry.timestamp.isoformat(),
                "metadata": entry.metadata,
                "tags": entry.tags
            }
        return None
    
    # =========================================================================
    # Prediction Operations
    # =========================================================================
    
    def _create_prediction_embedding(
        self,
        prediction: float,
        confidence: float,
        features: np.ndarray,
        dimension: int = 64
    ) -> np.ndarray:
        """Create embedding from model prediction."""
        base_features = [
            prediction,  # Predicted return/value
            confidence,  # Model confidence
            prediction * confidence,  # Weighted
            abs(prediction),  # Absolute magnitude
            1.0 if prediction > 0 else -1.0,  # Direction
        ]
        
        # Add feature importance (top 10)
        if len(features) > 0:
            top_features = np.sort(np.abs(features))[-10:]
            base_features.extend(top_features.tolist())
        else:
            base_features.extend([0.0] * 10)
        
        # Pad to dimension
        embedding = np.zeros(dimension, dtype=np.float32)
        embedding[:len(base_features)] = base_features[:dimension]
        
        # Normalize
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        
        return embedding
    
    def store_prediction(
        self,
        prediction: float,
        confidence: float,
        features: np.ndarray,
        metadata: dict | None = None
    ) -> str:
        """Store a model prediction."""
        if not self._collections_initialized:
            self.initialize()
        
        embedding = self._create_prediction_embedding(
            prediction, confidence, features, self.config.prediction_dimension
        )
        
        timestamp = datetime.now()
        pred_id = f"pred_{timestamp.strftime('%Y%m%d_%H%M%S')}"
        
        entry = VectorEntry(
            id=pred_id,
            vector=embedding,
            metadata={
                "prediction": float(prediction),
                "confidence": float(confidence),
                **(metadata or {})
            },
            timestamp=timestamp,
            collection=self.config.predictions_collection
        )
        
        self.db.add(entry, self.config.predictions_collection)
        self._maybe_save()
        
        return pred_id
    
    def check_prediction_drift(
        self,
        prediction: float,
        confidence: float,
        features: np.ndarray,
        window_size: int | None = None
    ) -> tuple[bool, float]:
        """
        Check if current prediction differs significantly from recent history.
        
        Args:
            prediction: Current prediction
            confidence: Current confidence
            features: Current features
            window_size: Number of recent predictions to compare
        
        Returns:
            (is_drift, average_similarity)
        """
        if not self._collections_initialized:
            self.initialize()
        
        window_size = window_size or self.config.reference_window_size
        
        # Get recent predictions
        recent = self.db.get_collection(self.config.predictions_collection)
        
        # Current embedding
        current = self._create_prediction_embedding(
            prediction, confidence, features, self.config.prediction_dimension
        )
        
        # Search for similar recent predictions
        results = self.db.search(
            current,
            k=min(window_size, recent.count()),
            collection=self.config.predictions_collection
        )
        
        if not results:
            return False, 1.0
        
        # Calculate average similarity
        avg_similarity = np.mean([r.score for r in results])
        
        # Check drift
        is_drift = avg_similarity < self.config.drift_threshold
        
        return is_drift, float(avg_similarity)
    
    # =========================================================================
    # Trade Operations
    # =========================================================================
    
    def _create_trade_embedding(
        self,
        entry_price: float,
        exit_price: float,
        position_size: float,
        duration_hours: float,
        side: str,
        dimension: int = 32
    ) -> np.ndarray:
        """Create embedding for a trade."""
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
        if side.lower() == "short":
            pnl_pct = -pnl_pct
        
        features = [
            pnl_pct,  # PnL %
            position_size / 10000,  # Normalized size
            duration_hours / 168,  # Normalized duration (week)
            1.0 if side.lower() == "long" else -1.0,
            abs(pnl_pct) * position_size,  # Risk-adjusted PnL
            (exit_price - entry_price) / entry_price if side.lower() == "long" 
                else (entry_price - exit_price) / entry_price,  # Absolute return
        ]
        
        # Pad
        embedding = np.zeros(dimension, dtype=np.float32)
        embedding[:len(features)] = features[:dimension]
        
        # Normalize
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        
        return embedding
    
    def store_trade(
        self,
        entry_price: float,
        exit_price: float,
        position_size: float,
        duration_hours: float,
        side: str,
        metadata: dict | None = None
    ) -> str:
        """Store a completed trade."""
        if not self._collections_initialized:
            self.initialize()
        
        embedding = self._create_trade_embedding(
            entry_price, exit_price, position_size, duration_hours, side,
            self.config.trade_dimension
        )
        
        timestamp = datetime.now()
        trade_id = f"trade_{timestamp.strftime('%Y%m%d_%H%M%S')}"
        
        entry = VectorEntry(
            id=trade_id,
            vector=embedding,
            metadata={
                "entry_price": float(entry_price),
                "exit_price": float(exit_price),
                "position_size": float(position_size),
                "duration_hours": float(duration_hours),
                "side": side,
                "pnl_pct": float(((exit_price - entry_price) / entry_price) * 100),
                **(metadata or {})
            },
            timestamp=timestamp,
            collection=self.config.trades_collection,
            tags=["winning" if exit_price > entry_price and side.lower() == "long" else "losing"]
        )
        
        self.db.add(entry, self.config.trades_collection)
        self._maybe_save()
        
        return trade_id
    
    def find_similar_trades(
        self,
        entry_price: float,
        position_size: float,
        side: str,
        k: int = 5
    ) -> list[dict]:
        """Find similar historical trades."""
        if not self._collections_initialized:
            self.initialize()
        
        # Create query with current position
        query_embedding = self._create_trade_embedding(
            entry_price, entry_price, position_size, 0, side,
            self.config.trade_dimension
        )
        
        results = self.db.search(
            query_embedding,
            k=k,
            collection=self.config.trades_collection
        )
        
        similar = []
        for r in results:
            similar.append({
                "id": r.entry.id,
                "similarity": r.score,
                "metadata": r.entry.metadata,
                "timestamp": r.entry.timestamp.isoformat()
            })
        
        return similar
    
    # =========================================================================
    # Analytics
    # =========================================================================
    
    def get_analytics(self, collection: str | None = None) -> dict:
        """Get analytics for collections."""
        if not self._collections_initialized:
            self.initialize()
        
        if collection:
            analytics = self.db.analyze(collection)
        else:
            # All collections
            analytics = self.db.analyze()
        
        return {
            "total_vectors": analytics.total_vectors,
            "collections": analytics.collections_count,
            "clusters": analytics.clusters_count,
            "oldest_entry": analytics.oldest_entry.isoformat() if analytics.oldest_entry else None,
            "newest_entry": analytics.newest_entry.isoformat() if analytics.newest_entry else None,
            "entries_per_day": analytics.entries_per_day,
            "metadata_fields": analytics.metadata_fields
        }
    
    def find_anomalies(
        self,
        collection: str,
        threshold: float = 3.0
    ) -> list[dict]:
        """Find anomalous entries in a collection."""
        if not self._collections_initialized:
            self.initialize()
        
        anomalies = self.db.find_anomalies(collection, threshold)
        
        return [
            {
                "id": a.id,
                "timestamp": a.timestamp.isoformat(),
                "metadata": a.metadata
            }
            for a in anomalies
        ]
    
    def cluster_patterns(self, n_clusters: int = 10) -> list[dict]:
        """Cluster price patterns."""
        if not self._collections_initialized:
            self.initialize()
        
        clusters = self.db.cluster(self.config.patterns_collection, n_clusters)
        
        return [
            {
                "id": c.id,
                "size": c.size,
                "avg_distance": c.avg_distance,
                "examples": c.examples
            }
            for c in clusters
        ]
    
    # =========================================================================
    # Maintenance
    # =========================================================================
    
    def cleanup(self) -> dict:
        """Run cleanup based on retention policies."""
        if not self._collections_initialized:
            self.initialize()
        
        return self.db.cleanup()
    
    def backup(self, path: str | None = None) -> str:
        """Create backup."""
        if not self._collections_initialized:
            self.initialize()
        
        return self.db.backup(path)
    
    def restore(self, path: str) -> None:
        """Restore from backup."""
        self.initialize()
        self.db.restore(path)
    
    def save(self) -> None:
        """Save current state."""
        self._save()
    
    def close(self) -> None:
        """Close and save."""
        self._save()


# ============================================================================
# Singleton Instance
# ============================================================================

# Global instance
_vector_db_manager: VectorDBManager | None = None


def get_vector_db_manager() -> VectorDBManager:
    """Get or create the global vector DB manager instance."""
    global _vector_db_manager
    if _vector_db_manager is None:
        _vector_db_manager = VectorDBManager()
    return _vector_db_manager


# ============================================================================
# Integration with Production Pipeline
# ============================================================================

def integrate_with_production_runner():
    """
    Example integration code for production_runner.py
    
    Add these methods to your production_runner.py:
    """
    return """
# Add to production_runner.py:

from production_hardening.vector_db_integration import get_vector_db_manager

class ProductionRunner:
    def __init__(self, ...):
        ...
        self.vector_db = get_vector_db_manager()
        self.vector_db.initialize()
    
    def on_prediction(self, prediction_data):
        '''Store prediction for drift detection'''
        self.vector_db.store_prediction(
            prediction=prediction_data['prediction'],
            confidence=prediction_data['confidence'],
            features=prediction_data['features'],
            metadata={
                'asset': prediction_data['ticker'],
                'model': prediction_data['model_type']
            }
        )
        
        # Check for drift
        is_drift, similarity = self.vector_db.check_prediction_drift(
            prediction_data['prediction'],
            prediction_data['confidence'],
            prediction_data['features']
        )
        
        if is_drift:
            self.logger.warning(f"Prediction drift detected: similarity={similarity}")
            # Trigger model retraining
    
    def on_price_update(self, prices, indicators):
        '''Find similar historical patterns'''
        similar = self.vector_db.find_similar_patterns(
            prices=prices,
            indicators=indicators,
            k=5
        )
        
        if similar:
            # Use pattern similarity to adjust confidence
            avg_similarity = np.mean([s['similarity'] for s in similar])
            self.logger.info(f"Pattern similarity: {avg_similarity:.3f}")
    
    def on_trade_close(self, trade):
        '''Store completed trade'''
        self.vector_db.store_trade(
            entry_price=trade.entry_price,
            exit_price=trade.exit_price,
            position_size=trade.position_size,
            duration_hours=trade.duration_hours,
            side=trade.side,
            metadata={
                'asset': trade.ticker,
                'strategy': trade.strategy
            }
        )
    
    def on_schedule(self):
        '''Scheduled tasks'''
        # Cleanup old entries
        cleaned = self.vector_db.cleanup()
        
        # Cluster patterns monthly
        if self.should_cluster():
            clusters = self.vector_db.cluster_patterns(n_clusters=10)
        
        # Find anomalies
        anomalies = self.vector_db.find_anomalies('predictions', threshold=3.0)
        if anomalies:
            self.logger.warning(f"Found {len(anomalies)} prediction anomalies")
        
        # Save
        self.vector_db.save()
"""


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    # Example usage
    manager = VectorDBManager()
    manager.initialize()
    
    # Store some patterns
    print("Storing sample patterns...")
    for i in range(10):
        prices = np.cumsum(np.random.randn(20) * 2 + 0.1)
        manager.store_price_pattern(
            prices=prices,
            indicators={"RSI_14": 55.0, "MACD": 0.5, "Volatility": 0.15},
            metadata={"asset": "BTC-USD", "timeframe": "1D"},
            tags=["bull"] if prices[-1] > prices[0] else ["bear"]
        )
    
    # Find similar patterns
    print("\nFinding similar patterns...")
    query_prices = np.cumsum(np.random.randn(20) * 2 + 0.1)
    similar = manager.find_similar_patterns(
        prices=query_prices,
        indicators={"RSI_14": 60.0, "MACD": 0.3, "Volatility": 0.12},
        k=3
    )
    
    for s in similar:
        print(f"  Pattern {s['id']}: similarity={s['similarity']:.3f}")
    
    # Store predictions
    print("\nStoring predictions...")
    for i in range(5):
        manager.store_prediction(
            prediction=np.random.randn() * 0.02,
            confidence=np.random.uniform(0.5, 0.95),
            features=np.random.randn(10),
            metadata={"ticker": "BTC-USD"}
        )
    
    # Check drift
    is_drift, similarity = manager.check_prediction_drift(
        prediction=0.01,
        confidence=0.8,
        features=np.random.randn(10)
    )
    print(f"\nDrift check: is_drift={is_drift}, similarity={similarity:.3f}")
    
    # Store trades
    print("\nStoring trades...")
    manager.store_trade(
        entry_price=50000,
        exit_price=52000,
        position_size=0.5,
        duration_hours=24,
        side="long",
        metadata={"asset": "BTC-USD", "strategy": "momentum"}
    )
    
    # Analytics
    print("\nAnalytics:")
    analytics = manager.get_analytics()
    print(f"  Total vectors: {analytics['total_vectors']}")
    print(f"  Collections: {analytics['collections']}")
    print(f"  Metadata fields: {analytics['metadata_fields']}")
    
    # Save
    manager.save()
    print("\nDone! Database saved.")
