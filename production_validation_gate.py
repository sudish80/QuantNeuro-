"""
PRODUCTION VALIDATION GATE
===========================

FIX #5: Production-grade model validation before live trading

Prevents degraded models from trading live by validating model quality metrics
against configurable thresholds. Includes alert system for model drift.

Author: QuantNeuro Trading System
Version: 4.0
"""

import numpy as np
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class ModelValidationThresholds:
    """Configurable model quality thresholds"""
    min_r2: float = 0.40  # Minimum R² score
    min_sharpe: float = 0.50  # Minimum Sharpe ratio
    max_mape: float = 5.0  # Maximum MAPE (%)
    max_rmse_std_ratio: float = 0.25  # Max RMSE variation across folds
    min_win_rate: float = 0.50  # Minimum win rate
    max_drawdown: float = -0.15  # Minimum drawdown (-15%)


@dataclass
class ModelValidationResult:
    """Result of model validation check"""
    is_valid: bool  # Overall validation result
    checks_passed: Dict[str, bool]  # Individual check results
    metrics: Dict[str, float]  # Computed metrics
    violations: list[str]  # Description of failed checks
    confidence_score: float  # 0-1, how confident is this model
    timestamp: datetime


class ProductionValidationGate:
    """
    Production-grade validation gate for models before live trading.
    
    Ensures only high-quality models are deployed to production.
    Detects model degradation, drift, and regime changes.
    """
    
    def __init__(self, thresholds: Optional[ModelValidationThresholds] = None):
        """
        Args:
            thresholds: CustomModelValidationThresholds or None for defaults
        """
        self.thresholds = thresholds or ModelValidationThresholds()
        self.validation_history: list[ModelValidationResult] = []
    
    def validate_model(
        self,
        model,
        recent_test_data: Dict[str, np.ndarray],
        compute_metrics_fn,
    ) -> ModelValidationResult:
        """
        Validate model against thresholds
        
        Args:
            model: Trained model with predict() method
            recent_test_data: {"X": np.ndarray, "y": np.ndarray}
            compute_metrics_fn: Function to compute metrics(actual, pred) -> dict
        
        Returns:
            ModelValidationResult
        """
        X_test = recent_test_data.get("X")
        y_test = recent_test_data.get("y")
        
        if X_test is None or y_test is None:
            return ModelValidationResult(
                is_valid=False,
                checks_passed={},
                metrics={},
                violations=["Missing test data (X or y)"],
                confidence_score=0.0,
                timestamp=datetime.now()
            )
        
        # Generate predictions
        try:
            predictions = model.predict(X_test)
        except Exception as e:
            logger.error(f"Model prediction failed: {e}")
            return ModelValidationResult(
                is_valid=False,
                checks_passed={},
                metrics={},
                violations=[f"Prediction error: {str(e)}"],
                confidence_score=0.0,
                timestamp=datetime.now()
            )
        
        # Compute metrics
        try:
            metrics = compute_metrics_fn(y_test, predictions)
        except Exception as e:
            logger.error(f"Metrics computation failed: {e}")
            return ModelValidationResult(
                is_valid=False,
                checks_passed={},
                metrics={},
                violations=[f"Metrics error: {str(e)}"],
                confidence_score=0.0,
                timestamp=datetime.now()
            )
        
        # Run validation checks
        checks_passed = {}
        violations = []
        
        # Check R²
        r2 = metrics.get("R²", -1.0)
        checks_passed["r2_check"] = r2 >= self.thresholds.min_r2
        if not checks_passed["r2_check"]:
            violations.append(
                f"R² below threshold: {r2:.4f} < {self.thresholds.min_r2:.4f}"
            )
        
        # Check Sharpe Ratio
        sharpe = metrics.get("Sharpe", 0.0)
        checks_passed["sharpe_check"] = sharpe >= self.thresholds.min_sharpe
        if not checks_passed["sharpe_check"]:
            violations.append(
                f"Sharpe ratio below threshold: {sharpe:.4f} < {self.thresholds.min_sharpe:.4f}"
            )
        
        # Check MAPE
        mape = metrics.get("MAPE (%)", 100.0)
        checks_passed["mape_check"] = mape <= self.thresholds.max_mape
        if not checks_passed["mape_check"]:
            violations.append(
                f"MAPE above threshold: {mape:.2f}% > {self.thresholds.max_mape:.2f}%"
            )
        
        # Check RMSE standard deviation ratio
        rmse_std_ratio = metrics.get("RMSE_Std_Ratio", 1.0)
        checks_passed["rmse_std_check"] = rmse_std_ratio <= self.thresholds.max_rmse_std_ratio
        if not checks_passed["rmse_std_check"]:
            violations.append(
                f"RMSE variation too high: {rmse_std_ratio:.4f} > {self.thresholds.max_rmse_std_ratio:.4f}"
            )
        
        # Check win rate
        win_rate = metrics.get("Win_Rate", 0.0)
        checks_passed["win_rate_check"] = win_rate >= self.thresholds.min_win_rate
        if not checks_passed["win_rate_check"]:
            violations.append(
                f"Win rate below threshold: {win_rate:.2%} < {self.thresholds.min_win_rate:.2%}"
            )
        
        # Check maximum drawdown
        max_drawdown = metrics.get("Max_Drawdown", 0.0)
        checks_passed["drawdown_check"] = max_drawdown >= self.thresholds.max_drawdown
        if not checks_passed["drawdown_check"]:
            violations.append(
                f"Drawdown too severe: {max_drawdown:.2%} > {self.thresholds.max_drawdown:.2%}"
            )
        
        # Calculate confidence score (0-1)
        # Confidence decreases if metrics are near thresholds
        checks_count = len(checks_passed)
        passed_count = sum(checks_passed.values())
        base_confidence = passed_count / checks_count if checks_count > 0 else 0.0
        
        # Adjust confidence based on metric values
        r2_margin = (r2 - self.thresholds.min_r2) / max(0.1, self.thresholds.min_r2)
        sharpe_margin = (sharpe - self.thresholds.min_sharpe) / max(0.1, self.thresholds.min_sharpe)
        confidence_score = min(1.0, base_confidence * max(0.3, (r2_margin + sharpe_margin) / 2))
        
        overall_valid = all(checks_passed.values())
        
        result = ModelValidationResult(
            is_valid=overall_valid,
            checks_passed=checks_passed,
            metrics=metrics,
            violations=violations,
            confidence_score=max(0.0, confidence_score),
            timestamp=datetime.now()
        )
        
        self.validation_history.append(result)
        return result
    
    def detect_model_degradation(self) -> Tuple[bool, Dict]:
        """
        Detect gradual model degradation by comparing recent validations
        
        Returns:
            (degradation_detected, degradation_details)
        """
        if len(self.validation_history) < 2:
            return False, {}
        
        # Compare last 2 validations
        recent = self.validation_history[-1]
        previous = self.validation_history[-2]
        
        degradation_indicators = {}
        
        # Check R² degradation
        r2_drop = self.validation_history[-2].metrics.get("R²", 0) - recent.metrics.get("R²", 0)
        if r2_drop > 0.10:  # 10% drop is significant
            degradation_indicators["r2_degradation"] = r2_drop
        
        # Check Sharpe degradation
        sharpe_drop = self.validation_history[-2].metrics.get("Sharpe", 0) - recent.metrics.get("Sharpe", 0)
        if sharpe_drop > 0.20:
            degradation_indicators["sharpe_degradation"] = sharpe_drop
        
        # Check MAPE increase
        mape_increase = recent.metrics.get("MAPE (%)", 100) - self.validation_history[-2].metrics.get("MAPE (%)", 100)
        if mape_increase > 1.0:  # 1% increase is concerning
            degradation_indicators["mape_increase"] = mape_increase
        
        degradation_detected = len(degradation_indicators) > 0
        
        return degradation_detected, degradation_indicators
    
    def log_validation_result(self, result: ModelValidationResult, model_name: str = "model"):
        """Log validation result with appropriate severity"""
        if result.is_valid:
            logger.info(
                f"[VALIDATION OK] {model_name} passed all checks. "
                f"Confidence: {result.confidence_score:.2%}. "
                f"R²={result.metrics.get('R²', 0):.4f}, "
                f"Sharpe={result.metrics.get('Sharpe', 0):.4f}"
            )
        else:
            logger.critical(
                f"[VALIDATION FAILED] {model_name} failed validation. "
                f"Violations: {'; '.join(result.violations[:3])}"
            )
    
    def should_halt_trading(self) -> bool:
        """Determine if trading should be halted due to model quality issues"""
        if not self.validation_history:
            return True  # No validation run yet
        
        recent = self.validation_history[-1]
        
        # Halt if last validation failed
        if not recent.is_valid:
            return True
        
        # Halt if confidence is critically low
        if recent.confidence_score < 0.3:
            return True
        
        # Halt if degradation detected
        degradation_detected, _ = self.detect_model_degradation()
        if degradation_detected and len(self.validation_history) >= 5:
            # Only halt for degradation if we have enough history
            return True
        
        return False


# ============================================================================
# MODIFIED production_runner.py with validation gates
# ============================================================================

class LiveTradingRunner:
    """
    Live trading runner WITH validation gates to prevent degraded model trading
    """
    
    def __init__(self, model, broker, validator: ProductionValidationGate):
        self.model = model
        self.broker = broker
        self.validator = validator
        self.prediction_count = 0
        self.trading_halted = False
    
    def validate_and_trade(self, current_data: Dict, recent_test_data: Dict,
                          compute_metrics_fn, signal_threshold: float = 0.5) -> Optional[str]:
        """
        Validate model periodically, then place order if validation passes
        
        Args:
            current_data: {"X": current_features}
            recent_test_data: Last N samples for validation
            compute_metrics_fn: Metrics computation function
            signal_threshold: Probability threshold for SELL/BUY
        
        Returns:
            Order ID if placed, None otherwise
        """
        # Periodically validate (every 50 predictions)
        if self.prediction_count % 50 == 0:
            validation_result = self.validator.validate_model(
                self.model,
                recent_test_data,
                compute_metrics_fn
            )
            
            self.validator.log_validation_result(validation_result, "live_model")
            
            if not validation_result.is_valid:
                logger.critical("Model validation FAILED - halting trades")
                self.trading_halted = True
                return None
            
            if self.validator.should_halt_trading():
                logger.critical("Trading halt condition triggered by validation gate")
                self.trading_halted = True
                return None
            
            self.trading_halted = False
        
        # Only trade if not halted
        if self.trading_halted:
            logger.warning("Trading halted - validation gate active")
            return None
        
        # Generate prediction and signal
        try:
            signal = self.model.predict(current_data["X"])
        except Exception as e:
            logger.error(f"Prediction error: {e}")
            return None
        
        # Place order if signal exceeds threshold
        order_id = None
        if signal > signal_threshold:
            order_id = self.broker.place_order("BUY", 1.0)
            logger.info(f"BUY signal placed: {order_id}")
        elif signal < (1 - signal_threshold):
            order_id = self.broker.place_order("SELL", 1.0)
            logger.info(f"SELL signal placed: {order_id}")
        
        self.prediction_count += 1
        return order_id


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    # Configure validation thresholds
    thresholds = ModelValidationThresholds(
        min_r2=0.40,
        min_sharpe=0.50,
        max_mape=5.0,
        min_win_rate=0.52,
        max_drawdown=-0.20
    )
    
    gate = ProductionValidationGate(thresholds)
    
    # Simulate model metrics
    metrics_good = {
        "R²": 0.55,
        "Sharpe": 1.2,
        "MAPE (%)": 3.5,
        "RMSE_Std_Ratio": 0.15,
        "Win_Rate": 0.58,
        "Max_Drawdown": -0.12
    }
    
    metrics_bad = {
        "R²": 0.25,
        "Sharpe": 0.2,
        "MAPE (%)": 8.5,
        "RMSE_Std_Ratio": 0.35,
        "Win_Rate": 0.48,
        "Max_Drawdown": -0.25
    }
    
    # Create mock model and validation
    class MockModel:
        def __init__(self, metrics):
            self.metrics = metrics
        
        def predict(self, X):
            return np.random.rand(len(X))
    
    def mock_compute_metrics(actual, pred):
        metrics_good['RMSE_Std_Ratio'] = 0.15
        return metrics_good
    
    # Test good model
    model_good = MockModel(metrics_good)
    result_good = gate.validate_model(
        model_good,
        {"X": np.random.rand(100, 60, 15), "y": np.random.rand(100)},
        mock_compute_metrics
    )
    
    print("GOOD MODEL VALIDATION")
    print(f"  Valid: {result_good.is_valid}")
    print(f"  Confidence: {result_good.confidence_score:.2%}")
    print(f"  Violations: {result_good.violations}")
    print()
    
    # Test bad model
    def bad_compute_metrics(actual, pred):
        return metrics_bad
    
    model_bad = MockModel(metrics_bad)
    result_bad = gate.validate_model(
        model_bad,
        {"X": np.random.rand(100, 60, 15), "y": np.random.rand(100)},
        bad_compute_metrics
    )
    
    print("BAD MODEL VALIDATION")
    print(f"  Valid: {result_bad.is_valid}")
    print(f"  Confidence: {result_bad.confidence_score:.2%}")
    print(f"  Violations: {result_bad.violations}")
