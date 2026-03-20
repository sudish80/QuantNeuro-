"""
PHASE 2 - FEATURE STORE & REPRODUCIBILITY

Versioned feature repository for ML reproducibility:
- Feature versioning (track all transformations)
- Feature snapshots (point-in-time consistency)
- Training/serving parity (prevent training-serving skew)
- Feature lineage (understand data dependencies)
- Offline/online consistency (batch vs real-time same logic)

Usage:
    store = FeatureStore(backend="postgres")
    
    # Register features
    store.register_feature_group(
        name="market_indicators",
        features=["sma_20", "rsi", "macd"],
        version="v1"
    )
    
    # Get snapshot at point in time
    snapshot = store.get_snapshot(
        tickers=["AAPL", "GOOGL"],
        date="2024-01-15",
        as_of_date="2024-01-14"  # Avoid look-ahead
    )
    
    # Ensure training-serving consistency
    consistency = store.check_consistency(
        training_set=train_features,
        serving_features=serve_features
    )
"""

import hashlib
import json
import logging
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS & CONSTANTS
# ============================================================================

class FeatureType(Enum):
    """Feature data type."""
    NUMERICAL = "NUMERICAL"
    CATEGORICAL = "CATEGORICAL"
    DATETIME = "DATETIME"


class FeatureStatus(Enum):
    """Feature lifecycle status."""
    EXPERIMENTAL = "EXPERIMENTAL"
    STAGING = "STAGING"
    PRODUCTION = "PRODUCTION"
    DEPRECATED = "DEPRECATED"


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class Feature:
    """Feature metadata."""
    name: str
    type: FeatureType
    description: str
    version: str  # e.g., "v1", "v2"
    status: FeatureStatus = FeatureStatus.EXPERIMENTAL
    source: str = ""  # Data source (API, database, etc)
    computation: str = ""  # How it's computed
    dependencies: List[str] = field(default_factory=list)  # Other features
    update_frequency: str = "DAILY"  # REALTIME, HOURLY, DAILY, etc
    missing_policy: str = "FORWARD_FILL"  # How to handle NaN
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class FeatureGroup:
    """Collection of related features."""
    name: str
    features: List[Feature]
    version: str
    namespace: str = "default"
    description: str = ""
    owner: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def get_feature_names(self) -> List[str]:
        """Get list of feature names."""
        return [f.name for f in self.features]


@dataclass
class FeatureSnapshot:
    """Point-in-time feature snapshot."""
    feature_group: str
    snapshot_date: date
    as_of_date: date  # When features were computed
    features: Dict[str, Dict[str, Any]]  # ticker -> {feature_name: value}
    checksum: str = ""  # Hash for validation
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FeatureLineage:
    """Trace of feature dependencies and transformations."""
    feature_name: str
    upstream_features: List[str]
    upstream_sources: List[str]  # Raw data sources
    transformation: str  # SQL, Python code, etc
    computed_at: datetime = field(default_factory=datetime.now)


# ============================================================================
# FEATURE REGISTRY
# ============================================================================

class FeatureRegistry:
    """Catalog of all features."""
    
    def __init__(self):
        self.features = {}  # (group, name, version) -> Feature
        self.groups = {}  # (group, version) -> FeatureGroup
        self.lineages = {}  # feature_name -> FeatureLineage
    
    def register_feature(
        self,
        group: str,
        name: str,
        type: FeatureType,
        description: str,
        version: str = "v1",
        computation: str = "",
        dependencies: List[str] = None
    ):
        """Register a new feature."""
        feature = Feature(
            name=name,
            type=type,
            description=description,
            version=version,
            computation=computation,
            dependencies=dependencies or []
        )
        
        key = (group, name, version)
        self.features[key] = feature
        logger.info(f"Registered feature: {group}/{name} v{version}")
    
    def get_feature(
        self,
        group: str,
        name: str,
        version: str = "v1"
    ) -> Optional[Feature]:
        """Get feature metadata."""
        key = (group, name, version)
        return self.features.get(key)
    
    def register_feature_group(
        self,
        name: str,
        namespace: str = "default",
        version: str = "v1",
        description: str = ""
    ) -> FeatureGroup:
        """Create new feature group."""
        group = FeatureGroup(
            name=name,
            features=[],
            version=version,
            namespace=namespace,
            description=description
        )
        
        key = (namespace, name, version)
        self.groups[key] = group
        logger.info(f"Created feature group: {namespace}/{name} v{version}")
        return group
    
    def add_to_group(
        self,
        group_name: str,
        features: List[Tuple[str, FeatureType, str]],  # (name, type, description)
        namespace: str = "default",
        version: str = "v1"
    ):
        """Add features to group."""
        key = (namespace, group_name, version)
        if key not in self.groups:
            self.register_feature_group(group_name, namespace, version)
        
        group = self.groups[key]
        for fname, ftype, fdesc in features:
            feature = Feature(
                name=fname,
                type=ftype,
                description=fdesc,
                version=version
            )
            if feature not in group.features:
                group.features.append(feature)
    
    def record_lineage(
        self,
        feature_name: str,
        upstream_features: List[str],
        upstream_sources: List[str],
        transformation: str
    ):
        """Record how feature is computed."""
        lineage = FeatureLineage(
            feature_name=feature_name,
            upstream_features=upstream_features,
            upstream_sources=upstream_sources,
            transformation=transformation
        )
        self.lineages[feature_name] = lineage


# ============================================================================
# FEATURE STORE
# ============================================================================

class FeatureStore:
    """Versioned feature repository."""
    
    def __init__(self, backend: str = "in_memory"):
        """
        Args:
            backend: "in_memory", "postgres", "s3", etc
        """
        self.backend = backend
        self.registry = FeatureRegistry()
        self.snapshots = {}  # (group, date) -> FeatureSnapshot
        self.feature_data = {}  # (group, ticker, date) -> {feature: value}
    
    # ========== REGISTRATION ==========
    
    def register_feature(
        self,
        group: str,
        name: str,
        type: FeatureType,
        description: str,
        version: str = "v1"
    ):
        """Register feature in registry."""
        self.registry.register_feature(group, name, type, description, version)
    
    def register_feature_group(
        self,
        name: str,
        features: List[Dict[str, Any]],
        version: str = "v1",
        namespace: str = "default"
    ):
        """Register feature group with features."""
        group = self.registry.register_feature_group(name, namespace, version)
        
        for feature_config in features:
            feature = Feature(
                name=feature_config["name"],
                type=feature_config.get("type", FeatureType.NUMERICAL),
                description=feature_config.get("description", ""),
                version=version,
                computation=feature_config.get("computation", ""),
                dependencies=feature_config.get("dependencies", [])
            )
            group.features.append(feature)
        
        return group
    
    # ========== STORAGE ==========
    
    def write_features(
        self,
        group: str,
        date_: date,
        features: Dict[str, Dict[str, Any]]  # ticker -> {feature_name: value}
    ):
        """Write feature snapshot."""
        snapshot = FeatureSnapshot(
            feature_group=group,
            snapshot_date=date_,
            as_of_date=date_,
            features=features,
            checksum=self._compute_checksum(features)
        )
        
        key = (group, date_)
        self.snapshots[key] = snapshot
        
        # Also store individual records
        for ticker, feature_dict in features.items():
            data_key = (group, ticker, date_)
            self.feature_data[data_key] = feature_dict
        
        logger.info(f"Wrote {len(features)} futures for {group}/{date_}")
    
    def read_features(
        self,
        group: str,
        tickers: List[str],
        date_: date,
        as_of_date: Optional[date] = None
    ) -> pd.DataFrame:
        """
        Read features with point-in-time consistency.
        
        Args:
            group: Feature group
            tickers: List of tickers
            date_: Date to fetch features for
            as_of_date: Safety check - features must be computed before this date
        
        Returns:
            DataFrame with index=ticker, columns=features
        """
        if as_of_date and date_ > as_of_date:
            raise ValueError(f"Look-ahead: feature date {date_} > as_of_date {as_of_date}")
        
        rows = []
        for ticker in tickers:
            key = (group, ticker, date_)
            if key in self.feature_data:
                feature_dict = self.feature_data[key].copy()
                feature_dict["ticker"] = ticker
                rows.append(feature_dict)
        
        if not rows:
            logger.warning(f"No features found for {group}/{date_}")
            return pd.DataFrame()
        
        df = pd.DataFrame(rows)
        if "ticker" in df.columns:
            df.set_index("ticker", inplace=True)
        
        return df
    
    def get_snapshot(
        self,
        group: str,
        date_: date,
        as_of_date: Optional[date] = None
    ) -> Optional[FeatureSnapshot]:
        """Get feature snapshot."""
        key = (group, date_)
        snapshot = self.snapshots.get(key)
        
        if snapshot and as_of_date and date_ > as_of_date:
            logger.warning(f"Look-ahead risk detected for {group}/{date_}")
        
        return snapshot
    
    # ========== CONSISTENCY CHECKS ==========
    
    def check_consistency(
        self,
        training_features: pd.DataFrame,
        serving_features: pd.DataFrame
    ) -> Dict[str, Any]:
        """
        Detect training-serving skew.
        
        Args:
            training_features: Features used during training
            serving_features: Features used during inference
        
        Returns:
            Consistency report with any mismatches
        """
        issues = []
        
        # Check columns match
        train_cols = set(training_features.columns)
        serve_cols = set(serving_features.columns)
        
        if train_cols != serve_cols:
            missing = train_cols - serve_cols
            extra = serve_cols - train_cols
            issues.append({
                "type": "SCHEMA_MISMATCH",
                "missing_in_serving": list(missing),
                "extra_in_serving": list(extra)
            })
        
        # Check statistics match
        common_cols = train_cols & serve_cols
        for col in common_cols:
            train_mean = training_features[col].mean()
            serve_mean = serving_features[col].mean()
            
            # Allow 10% deviation
            if abs(serve_mean - train_mean) / abs(train_mean + 1e-6) > 0.1:
                issues.append({
                    "type": "DISTRIBUTION_SKEW",
                    "feature": col,
                    "train_mean": float(train_mean),
                    "serve_mean": float(serve_mean)
                })
        
        return {
            "consistent": len(issues) == 0,
            "issues": issues,
            "num_issues": len(issues)
        }
    
    def detect_data_drift(
        self,
        reference_features: pd.DataFrame,
        current_features: pd.DataFrame,
        threshold: float = 0.1
    ) -> Dict[str, float]:
        """
        Detect feature drift using Kolmogorov-Smirnov test.
        
        Returns:
            KS statistics per feature
        """
        drift_stats = {}
        
        for col in reference_features.columns:
            if col not in current_features.columns:
                continue
            
            ref_data = reference_features[col].dropna().values
            curr_data = current_features[col].dropna().values
            
            if len(ref_data) == 0 or len(curr_data) == 0:
                drift_stats[col] = 0.0
                continue
            
            # Kolmogorov-Smirnov test
            ref_sorted = np.sort(ref_data)
            curr_sorted = np.sort(curr_data)
            
            ref_cdf = np.arange(1, len(ref_sorted) + 1) / len(ref_sorted)
            curr_cdf = np.arange(1, len(curr_sorted) + 1) / len(curr_sorted)
            
            # Simple KS approximation
            ks_stat = max(np.max(np.abs(ref_cdf - np.interp(ref_sorted, curr_sorted, curr_cdf))), 0.0)
            drift_stats[col] = ks_stat
        
        return drift_stats
    
    # ========== VERSIONING ==========
    
    def promote_feature(
        self,
        group: str,
        feature_name: str,
        from_version: str,
        to_status: FeatureStatus
    ):
        """Promote feature through lifecycle."""
        feature = self.registry.get_feature(group, feature_name, from_version)
        if feature:
            feature.status = to_status
            logger.info(f"Promoted {group}/{feature_name} to {to_status.value}")
    
    def version_feature_group(
        self,
        old_name: str,
        old_version: str,
        new_version: str,
        changes: str = ""
    ) -> FeatureGroup:
        """Create new version of feature group."""
        logger.info(f"Creating new version {new_version} of feature group {old_name}")
        logger.info(f"  Changes: {changes}")
        
        # Copy with new version
        new_group = self.registry.register_feature_group(old_name, version=new_version)
        return new_group
    
    # ========== UTILITIES ==========
    
    def _compute_checksum(self, data: Dict) -> str:
        """Compute checksum of feature data."""
        json_str = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(json_str.encode()).hexdigest()[:16]
    
    def get_feature_stats(
        self,
        group: str,
        feature_name: str,
        date_range: Tuple[date, date]
    ) -> Dict[str, float]:
        """Get statistics for feature over date range."""
        start_date, end_date = date_range
        values = []
        
        current = start_date
        while current <= end_date:
            # Collect all values for this feature across all tickers
            for ticker in ["AAPL", "GOOGL", "MSFT"]:  # Example
                key = (group, ticker, current)
                if key in self.feature_data:
                    feature_dict = self.feature_data[key]
                    if feature_name in feature_dict:
                        val = feature_dict[feature_name]
                        if isinstance(val, (int, float)):
                            values.append(val)
            
            current += timedelta(days=1)
        
        if not values:
            return {"error": f"No data found for {group}/{feature_name}"}
        
        return {
            "mean": float(np.mean(values)),
            "std": float(np.std(values)),
            "min": float(np.min(values)),
            "max": float(np.max(values)),
            "count": len(values)
        }


# ============================================================================
# INTEGRATION UTILITIES
# ============================================================================

def create_production_feature_store() -> FeatureStore:
    """Factory function to create pre-configured feature store."""
    store = FeatureStore(backend="postgres")
    
    # Register market indicators
    store.register_feature_group(
        name="market_indicators",
        features=[
            {"name": "sma_20", "type": FeatureType.NUMERICAL, "description": "20-day SMA"},
            {"name": "sma_50", "type": FeatureType.NUMERICAL, "description": "50-day SMA"},
            {"name": "rsi", "type": FeatureType.NUMERICAL, "description": "RSI (14)"},
            {"name": "macd", "type": FeatureType.NUMERICAL, "description": "MACD signal"},
            {"name": "atr", "type": FeatureType.NUMERICAL, "description": "Average True Range"},
            {"name": "bb_upper", "type": FeatureType.NUMERICAL, "description": "Bollinger Band upper"},
            {"name": "bb_lower", "type": FeatureType.NUMERICAL, "description": "Bollinger Band lower"},
        ],
        version="v1"
    )
    
    # Register sentiment features
    store.register_feature_group(
        name="sentiment",
        features=[
            {"name": "news_sentiment", "type": FeatureType.NUMERICAL, "description": "News sentiment score"},
            {"name": "social_sentiment", "type": FeatureType.NUMERICAL, "description": "Social media sentiment"},
            {"name": "insider_signal", "type": FeatureType.NUMERICAL, "description": "Insider transaction signal"},
        ],
        version="v1"
    )
    
    # Register volatility features
    store.register_feature_group(
        name="volatility",
        features=[
            {"name": "realized_vol", "type": FeatureType.NUMERICAL, "description": "Realized volatility"},
            {"name": "implied_vol", "type": FeatureType.NUMERICAL, "description": "Implied volatility (VIX)"},
            {"name": "vol_skew", "type": FeatureType.NUMERICAL, "description": "Volatility skew"},
        ],
        version="v1"
    )
    
    return store
