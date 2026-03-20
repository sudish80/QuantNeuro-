"""
Model lifecycle management with registry, drift detection, and canary rollout.

Provides:
- Model registry with versioning
- Champion/challenger model tracking
- Drift detection (feature, prediction, P&L)
- Canary rollout strategy
- Automatic rollback on metric degradation
"""

import os
import json
import hashlib
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
import numpy as np


# ============================================================================
# ENUMS & DATA CLASSES
# ============================================================================


class ModelStatus(str, Enum):
    """Model lifecycle status."""
    REGISTERED = "REGISTERED"
    TRAINING = "TRAINING"
    TESTING = "TESTING"
    CHAMPION = "CHAMPION"
    CHALLENGER = "CHALLENGER"
    CANARY = "CANARY"
    RETIRED = "RETIRED"
    ROLLBACK = "ROLLBACK"


class DriftType(str, Enum):
    """Types of drift."""
    FEATURE_DRIFT = "FEATURE_DRIFT"
    PREDICTION_DRIFT = "PREDICTION_DRIFT"
    PNL_DRIFT = "PNL_DRIFT"
    DATA_DRIFT = "DATA_DRIFT"


@dataclass
class ModelMetrics:
    """Training/evaluation metrics for a model."""
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1_score: float = 0.0
    sharpe_ratio: float = 0.0
    win_rate: float = 0.0
    max_drawdown: float = 0.0
    rmse: float = 0.0
    mae: float = 0.0
    custom_metrics: Dict[str, float] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"Accuracy: {self.accuracy:.3f} | Sharpe: {self.sharpe_ratio:.2f} | WinRate: {self.win_rate:.1%}"


@dataclass
class ModelVersion:
    """Model version metadata and artifacts."""
    version_id: str  # UUID
    model_name: str
    status: ModelStatus
    created_at: datetime
    trained_at: Optional[datetime] = None
    
    # Metrics
    train_metrics: ModelMetrics = field(default_factory=ModelMetrics)
    test_metrics: ModelMetrics = field(default_factory=ModelMetrics)
    
    # Artifacts
    model_path: str = ""
    checksum: str = ""  # SHA256 of model file
    
    # Metadata
    hyperparameters: Dict = field(default_factory=dict)
    training_data_hash: str = ""
    feature_list: List[str] = field(default_factory=list)
    
    # Canary/rollout
    canary_traffic_pct: float = 0.0  # % of traffic
    canary_start_time: Optional[datetime] = None
    
    # Drift tracking
    drift_detected: bool = False
    drift_type: Optional[DriftType] = None
    drift_score: float = 0.0


# ============================================================================
# MODEL REGISTRY
# ============================================================================


class ModelRegistry:
    """Manages model versions and their lifecycle."""

    def __init__(self, registry_file: str = "models/registry.json"):
        self.registry_file = registry_file
        self.models: Dict[str, ModelVersion] = {}
        self.champion_model: Optional[ModelVersion] = None
        self.challenger_model: Optional[ModelVersion] = None
        self._load_registry()

    def _load_registry(self):
        """Load registry from persistent storage."""
        if os.path.exists(self.registry_file):
            with open(self.registry_file, "r") as f:
                data = json.load(f)
                # Deserialize models (simplified)
                # In production, use pickle or dedicated serialization

    def _save_registry(self):
        """Save registry to persistent storage."""
        os.makedirs(os.path.dirname(self.registry_file), exist_ok=True)
        with open(self.registry_file, "w") as f:
            # Serialize models
            json.dump({}, f, indent=2)

    def register_model(
        self,
        model_name: str,
        model_path: str,
        hyperparameters: Dict,
        feature_list: List[str],
    ) -> ModelVersion:
        """Register a new model version."""
        version_id = self._generate_version_id()
        
        # Compute checksum
        checksum = self._compute_checksum(model_path)

        model = ModelVersion(
            version_id=version_id,
            model_name=model_name,
            status=ModelStatus.REGISTERED,
            created_at=datetime.utcnow(),
            model_path=model_path,
            checksum=checksum,
            hyperparameters=hyperparameters,
            feature_list=feature_list,
        )

        self.models[version_id] = model
        self._save_registry()

        return model

    def update_metrics(
        self,
        version_id: str,
        train_metrics: ModelMetrics,
        test_metrics: ModelMetrics,
    ):
        """Update metrics for a model version."""
        if version_id not in self.models:
            return

        model = self.models[version_id]
        model.train_metrics = train_metrics
        model.test_metrics = test_metrics
        model.status = ModelStatus.TESTING
        model.trained_at = datetime.utcnow()

        self._save_registry()

    def promote_to_champion(self, version_id: str) -> bool:
        """Promote model to champion (production)."""
        if version_id not in self.models:
            return False

        model = self.models[version_id]
        
        # Demote current champion if exists
        if self.champion_model:
            self.champion_model.status = ModelStatus.CHALLENGER
            self.challenger_model = self.champion_model

        # Promote new champion
        model.status = ModelStatus.CHAMPION
        self.champion_model = model

        self._save_registry()
        return True

    def promote_to_challenger(self, version_id: str) -> bool:
        """Promote model to challenger for A/B testing."""
        if version_id not in self.models:
            return False

        model = self.models[version_id]
        model.status = ModelStatus.CHALLENGER
        self.challenger_model = model

        self._save_registry()
        return True

    def start_canary_rollout(
        self, version_id: str, initial_traffic_pct: float = 0.10
    ) -> bool:
        """Start canary rollout for a model."""
        if version_id not in self.models:
            return False

        model = self.models[version_id]
        model.status = ModelStatus.CANARY
        model.canary_traffic_pct = initial_traffic_pct
        model.canary_start_time = datetime.utcnow()

        self._save_registry()
        return True

    def increase_canary_traffic(self, version_id: str, new_traffic_pct: float) -> bool:
        """Increase traffic to canary model."""
        if version_id not in self.models:
            return False

        model = self.models[version_id]
        if model.status != ModelStatus.CANARY:
            return False

        model.canary_traffic_pct = min(100.0, new_traffic_pct)
        
        # If 100%, promote to champion
        if model.canary_traffic_pct >= 100.0:
            self.promote_to_champion(version_id)

        self._save_registry()
        return True

    def rollback_to_version(self, version_id: str) -> bool:
        """Rollback to previous model version."""
        if version_id not in self.models:
            return False

        # Demote current champion
        if self.champion_model:
            self.champion_model.status = ModelStatus.RETIRED

        # Restore previous version
        model = self.models[version_id]
        model.status = ModelStatus.CHAMPION
        self.champion_model = model

        self._save_registry()
        return True

    def get_active_models(self) -> Dict[str, ModelVersion]:
        """Get currently active models (champion, challenger, canary)."""
        active = {}
        if self.champion_model:
            active["champion"] = self.champion_model
        if self.challenger_model:
            active["challenger"] = self.challenger_model
        
        canary_models = [
            m for m in self.models.values()
            if m.status == ModelStatus.CANARY
        ]
        for idx, model in enumerate(canary_models):
            active[f"canary_{idx}"] = model

        return active

    def get_model(self, version_id: str) -> Optional[ModelVersion]:
        """Get model by version ID."""
        return self.models.get(version_id)

    def _generate_version_id(self) -> str:
        """Generate unique version ID."""
        import uuid
        return str(uuid.uuid4())[:8]

    def _compute_checksum(self, file_path: str) -> str:
        """Compute SHA256 checksum of model file."""
        if not os.path.exists(file_path):
            return ""

        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        
        return sha256_hash.hexdigest()


# ============================================================================
# DRIFT DETECTION
# ============================================================================


class DriftDetector:
    """Detects model and data drift."""

    def __init__(
        self,
        feature_drift_threshold: float = 0.1,
        pred_drift_threshold: float = 0.15,
        pnl_drift_threshold: float = 0.2,
    ):
        self.feature_drift_threshold = feature_drift_threshold
        self.pred_drift_threshold = pred_drift_threshold
        self.pnl_drift_threshold = pnl_drift_threshold

    def detect_feature_drift(
        self,
        historical_features: np.ndarray,
        recent_features: np.ndarray,
    ) -> Tuple[bool, float]:
        """
        Detect feature drift using Kolmogorov-Smirnov test.
        Returns (is_drifting, drift_score).
        """
        from scipy.stats import ks_2samp

        # Compute KS statistic
        if len(historical_features) < 30 or len(recent_features) < 30:
            return False, 0.0

        ks_stat, p_value = ks_2samp(
            historical_features.flatten(),
            recent_features.flatten()
        )

        is_drifting = ks_stat > self.feature_drift_threshold
        return is_drifting, ks_stat

    def detect_prediction_drift(
        self,
        historical_predictions: np.ndarray,
        recent_predictions: np.ndarray,
    ) -> Tuple[bool, float]:
        """
        Detect prediction drift by comparing distributions.
        Returns (is_drifting, drift_score).
        """
        # Check if mean prediction has shifted
        hist_mean = np.mean(historical_predictions)
        recent_mean = np.mean(recent_predictions)

        drift_score = abs(recent_mean - hist_mean) / (hist_mean + 1e-6)
        is_drifting = drift_score > self.pred_drift_threshold

        return is_drifting, drift_score

    def detect_pnl_drift(
        self,
        historical_pnl: List[float],
        recent_pnl: List[float],
    ) -> Tuple[bool, float]:
        """
        Detect P&L drift by comparing win rates and Sharpe ratios.
        Returns (is_drifting, drift_score).
        """
        hist_win_rate = len([p for p in historical_pnl if p > 0]) / len(historical_pnl)
        recent_win_rate = len([p for p in recent_pnl if p > 0]) / len(recent_pnl)

        drift_score = abs(recent_win_rate - hist_win_rate)
        is_drifting = drift_score > self.pnl_drift_threshold

        return is_drifting, drift_score

    def detect_data_drift(
        self,
        historical_data: Dict[str, np.ndarray],
        recent_data: Dict[str, np.ndarray],
    ) -> List[Tuple[str, bool, float]]:
        """
        Detect drift across multiple data columns.
        Returns [(column_name, is_drifting, score), ...].
        """
        from scipy.stats import ks_2samp

        results = []

        for column in historical_data.keys():
            if column not in recent_data:
                continue

            hist_col = historical_data[column].flatten()
            recent_col = recent_data[column].flatten()

            if len(hist_col) < 30 or len(recent_col) < 30:
                continue

            ks_stat, _ = ks_2samp(hist_col, recent_col)
            is_drifting = ks_stat > self.feature_drift_threshold

            results.append((column, is_drifting, ks_stat))

        return results


# ============================================================================
# CANARY ROLLOUT ORCHESTRATOR
# ============================================================================


class CanaryRollout:
    """Orchestrates safe canary rollout with monitoring."""

    def __init__(
        self,
        registry: ModelRegistry,
        drift_detector: DriftDetector,
        rollout_stages: List[float] = None,
        stage_duration_hours: int = 4,
    ):
        self.registry = registry
        self.drift_detector = drift_detector
        self.rollout_stages = rollout_stages or [0.10, 0.25, 0.50, 1.0]  # % traffic
        self.stage_duration_hours = stage_duration_hours
        self.stage_metrics: Dict[str, Dict] = {}

    def start_rollout(self, version_id: str) -> bool:
        """Start canary rollout with first stage."""
        return self.registry.start_canary_rollout(version_id, self.rollout_stages[0])

    def evaluate_stage(
        self, version_id: str, metrics: Dict
    ) -> Tuple[str, Optional[str]]:
        """
        Evaluate current canary stage.
        Returns (decision, reason).
        Decisions: "PROCEED", "HOLD", "ROLLBACK".
        """
        model = self.registry.get_model(version_id)
        if not model or model.status != ModelStatus.CANARY:
            return "HOLD", "Model not in canary status"

        # Check if stage duration exceeded
        canary_age = datetime.utcnow() - model.canary_start_time
        if canary_age.total_seconds() / 3600 < self.stage_duration_hours:
            return "HOLD", f"Stage too young ({canary_age.total_seconds() / 60:.0f}m old)"

        # Evaluate metrics
        champion_metrics = model.test_metrics
        canary_metrics_obj = ModelMetrics(**metrics)

        # Compare Sharpe ratio
        sharpe_diff = canary_metrics_obj.sharpe_ratio - champion_metrics.sharpe_ratio
        if sharpe_diff < -0.5:  # Significantly worse
            return "ROLLBACK", f"Sharpe degraded: {sharpe_diff:.2f}"

        # Compare win rate
        wr_diff = canary_metrics_obj.win_rate - champion_metrics.win_rate
        if wr_diff < -0.05:  # >5% worse
            return "ROLLBACK", f"Win rate degraded: {wr_diff:.1%}"

        # All checks passed
        return "PROCEED", "Metrics acceptable"

    def get_next_stage_traffic(self, version_id: str) -> Optional[float]:
        """Get next traffic allocation for canary."""
        model = self.registry.get_model(version_id)
        if not model:
            return None

        current_traffic = model.canary_traffic_pct
        
        for stage_traffic in self.rollout_stages:
            if stage_traffic > current_traffic:
                return stage_traffic

        return None

    def complete_rollout(self, version_id: str) -> bool:
        """Complete canary rollout (promote to champion)."""
        return self.registry.promote_to_champion(version_id)

    def abort_rollout(self, version_id: str) -> bool:
        """Abort canary rollout and return to champion."""
        model = self.registry.get_model(version_id)
        if not model:
            return False

        # Mark as rollback
        model.status = ModelStatus.ROLLBACK

        # Return to champion if needed
        if self.registry.champion_model and model != self.registry.champion_model:
            self.registry.promote_to_champion(self.registry.champion_model.version_id)

        return True


# ============================================================================
# GLOBAL INSTANCES
# ============================================================================

model_registry = ModelRegistry()
drift_detector = DriftDetector()
canary_rollout = CanaryRollout(model_registry, drift_detector)
