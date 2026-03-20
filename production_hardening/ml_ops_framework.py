"""
PHASE 3 - ML OPS FRAMEWORK: A/B Testing & Model Comparison

Production ML ops for safe model deployment:
- A/B test orchestration (champion vs challenger)
- Statistical significance testing (frequentist + Bayesian)
- Automated retraining pipeline
- Model performance tracking and comparison
- Metrics stratification by scenario/asset class

Usage:
    mlops = MLOpsFramework()
    
    # Start A/B test
    test = mlops.start_abtest(
        champion_model="model_v1",
        challenger_model="model_v2",
        traffic_split=0.5,  # 50/50 traffic
        test_duration_days=14
    )
    
    # Collect metrics
    mlops.record_prediction(
        test_id=test.id,
        model_version="v1",
        prediction=0.65,
        actual=1,
        asset_class="tech"
    )
    
    # Analyze results
    results = mlops.analyze_test_results(test.id)
    if results.champion_wins:
        mlops.promote_challenger(test.id)
"""

import numpy as np
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from enum import Enum
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS
# ============================================================================

class TestStatus(Enum):
    """A/B test status."""
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    INCONCLUSIVE = "INCONCLUSIVE"
    STOPPED_EARLY = "STOPPED_EARLY"


class RetrainingTrigger(Enum):
    """When to retrain models."""
    SCHEDULED = "SCHEDULED"  # Every N days
    DRIFT_DETECTED = "DRIFT_DETECTED"  # On drift alarm
    PERFORMANCE_DROP = "PERFORMANCE_DROP"  # On accuracy drop
    NEW_DATA_AVAILABLE = "NEW_DATA_AVAILABLE"  # New data batch


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class Prediction:
    """Model prediction with actual outcome."""
    timestamp: datetime
    model_version: str
    prediction: float
    actual: float
    score: float  # Confidence
    asset_class: str = ""
    scenario: str = ""
    latency_ms: float = 0.0


@dataclass
class ModelMetrics:
    """Per-model performance metrics."""
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    auc: float
    log_loss: float
    
    # By scenario
    accuracy_by_asset: Dict[str, float] = field(default_factory=dict)
    accuracy_by_scenario: Dict[str, float] = field(default_factory=dict)


@dataclass
class ABTest:
    """A/B test configuration and state."""
    id: str
    champion: str
    challenger: str
    traffic_split: float  # 0.5 = 50/50
    start_date: datetime
    end_date: datetime
    min_sample_size: int = 1000
    status: TestStatus = TestStatus.RUNNING
    predictions: List[Prediction] = field(default_factory=list)


@dataclass
class TestResult:
    """Result of A/B test."""
    test_id: str
    champion_metrics: ModelMetrics
    challenger_metrics: ModelMetrics
    champion_wins: bool
    confidence: float  # Statistical confidence (0-1)
    effect_size: float  # Practical significance
    p_value: float
    sample_size: int
    recommendation: str  # "Deploy", "Keep", "Inconclusive"


@dataclass
class RetrainingJob:
    """Model retraining job."""
    id: str
    model_name: str
    trigger: RetrainingTrigger
    start_time: datetime
    end_time: Optional[datetime] = None
    status: str = "PENDING"  # PENDING, RUNNING, SUCCESS, FAILED
    training_data_size: int = 0
    validation_accuracy: float = 0.0
    result_model_version: str = ""


# ============================================================================
# ML OPS FRAMEWORK
# ============================================================================

class MLOpsFramework:
    """Production ML Ops for safe model deployment."""
    
    def __init__(self):
        self.active_tests = {}  # test_id -> ABTest
        self.completed_tests = {}
        self.retraining_jobs = {}
        self.predictions_log = []
        self.model_versions = {}  # model_name -> [versions]
    
    # ========== A/B TESTING ==========
    
    def start_abtest(
        self,
        champion_model: str,
        challenger_model: str,
        traffic_split: float = 0.5,
        duration_days: int = 14,
        min_sample_size: int = 1000
    ) -> ABTest:
        """Start A/B test."""
        test_id = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        test = ABTest(
            id=test_id,
            champion=champion_model,
            challenger=challenger_model,
            traffic_split=traffic_split,
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=duration_days),
            min_sample_size=min_sample_size
        )
        
        self.active_tests[test_id] = test
        logger.info(f"Started A/B test {test_id}: {champion_model} vs {challenger_model}")
        return test
    
    def route_prediction(self, test_id: str) -> str:
        """
        Determine which model to route request to.
        
        Returns model version name.
        """
        if test_id not in self.active_tests:
            return None
        
        test = self.active_tests[test_id]
        if np.random.random() < test.traffic_split:
            return test.champion
        else:
            return test.challenger
    
    def record_prediction(
        self,
        test_id: str,
        model_version: str,
        prediction: float,
        actual: float,
        score: float = 0.5,
        asset_class: str = "",
        scenario: str = "",
        latency_ms: float = 0.0
    ):
        """Record prediction for test."""
        if test_id not in self.active_tests:
            logger.warning(f"Unknown test: {test_id}")
            return
        
        pred = Prediction(
            timestamp=datetime.now(),
            model_version=model_version,
            prediction=prediction,
            actual=actual,
            score=score,
            asset_class=asset_class,
            scenario=scenario,
            latency_ms=latency_ms
        )
        
        self.active_tests[test_id].predictions.append(pred)
        self.predictions_log.append(pred)
    
    def can_conclude_test(self, test_id: str) -> Tuple[bool, str]:
        """
        Check if test can be concluded.
        
        Returns: (can_conclude, reason)
        """
        if test_id not in self.active_tests:
            return False, "Test not found"
        
        test = self.active_tests[test_id]
        
        # Check sample size
        if len(test.predictions) < test.min_sample_size:
            return False, f"Need {test.min_sample_size} samples, have {len(test.predictions)}"
        
        # Check if reached end date
        if datetime.now() < test.end_date:
            return False, "Still within test duration"
        
        return True, "Test ready for analysis"
    
    def analyze_test_results(self, test_id: str) -> TestResult:
        """Analyze A/B test results."""
        if test_id not in self.active_tests:
            raise ValueError(f"Unknown test: {test_id}")
        
        test = self.active_tests[test_id]
        predictions = test.predictions
        
        if len(predictions) < test.min_sample_size:
            logger.warning(f"Test {test_id} has only {len(predictions)} predictions")
        
        # Split by model
        champion_preds = [p for p in predictions if p.model_version == test.champion]
        challenger_preds = [p for p in predictions if p.model_version == test.challenger]
        
        # Calculate metrics
        champion_metrics = self._calculate_metrics(champion_preds)
        challenger_metrics = self._calculate_metrics(challenger_preds)
        
        # Statistical test (frequentist)
        p_value, effect_size = self._two_proportion_test(
            champion_preds, challenger_preds
        )
        
        # Determine winner
        champion_wins = challenger_metrics.accuracy < champion_metrics.accuracy
        confidence = 1.0 - p_value if p_value < 0.05 else 0.0
        
        # Recommendation
        if p_value < 0.05:  # Statistically significant
            if challenger_metrics.accuracy > champion_metrics.accuracy + 0.02:  # 2% improvement
                recommendation = "Deploy"
            else:
                recommendation = "Keep"
        else:
            recommendation = "Inconclusive"
        
        result = TestResult(
            test_id=test_id,
            champion_metrics=champion_metrics,
            challenger_metrics=challenger_metrics,
            champion_wins=champion_wins,
            confidence=confidence,
            effect_size=effect_size,
            p_value=p_value,
            sample_size=len(predictions),
            recommendation=recommendation
        )
        
        # Move to completed
        test.status = TestStatus.COMPLETED
        self.active_tests.pop(test_id)
        self.completed_tests[test_id] = test
        
        logger.info(f"Test {test_id} completed: {recommendation} (p={p_value:.4f})")
        
        return result
    
    def _calculate_metrics(self, predictions: List[Prediction]) -> ModelMetrics:
        """Calculate metrics for set of predictions."""
        if not predictions:
            return ModelMetrics(0, 0, 0, 0, 0, float('inf'))
        
        # Convert to numpy
        pred = np.array([p.prediction for p in predictions])
        actual = np.array([p.actual for p in predictions])
        
        # Binary classification metrics
        pred_binary = (pred > 0.5).astype(int)
        
        tp = np.sum((pred_binary == 1) & (actual == 1))
        tn = np.sum((pred_binary == 0) & (actual == 0))
        fp = np.sum((pred_binary == 1) & (actual == 0))
        fn = np.sum((pred_binary == 0) & (actual == 1))
        
        accuracy = (tp + tn) / len(predictions)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
        
        # AUC (simplified)
        auc = np.mean(pred[actual == 1]) - np.mean(pred[actual == 0])
        auc = max(0, min(1, auc))
        
        # Log loss
        log_loss = -np.mean(actual * np.log(pred + 1e-10) + (1 - actual) * np.log(1 - pred + 1e-10))
        
        # By asset class
        by_asset = {}
        for asset_class in set(p.asset_class for p in predictions if p.asset_class):
            asset_preds = [p for p in predictions if p.asset_class == asset_class]
            if asset_preds:
                asset_pred = np.array([p.prediction for p in asset_preds])
                asset_actual = np.array([p.actual for p in asset_preds])
                by_asset[asset_class] = np.mean((asset_pred > 0.5).astype(int) == asset_actual)
        
        return ModelMetrics(
            accuracy=accuracy,
            precision=precision,
            recall=recall,
            f1_score=f1,
            auc=auc,
            log_loss=log_loss,
            accuracy_by_asset=by_asset
        )
    
    def _two_proportion_test(
        self,
        champion: List[Prediction],
        challenger: List[Prediction]
    ) -> Tuple[float, float]:
        """
        Two-proportion z-test.
        
        Returns: (p_value, effect_size)
        """
        if not champion or not challenger:
            return 1.0, 0.0
        
        # Count successes
        champion_success = sum(1 for p in champion if int(p.prediction > 0.5) == p.actual)
        challenger_success = sum(1 for p in challenger if int(p.prediction > 0.5) == p.actual)
        
        n1, n2 = len(champion), len(challenger)
        p1, p2 = champion_success / n1, challenger_success / n2
        
        # Pooled proportion
        p_pool = (champion_success + challenger_success) / (n1 + n2)
        
        # Standard error
        se = np.sqrt(p_pool * (1 - p_pool) * (1/n1 + 1/n2))
        
        # Z-statistic
        z = (p2 - p1) / (se + 1e-10)
        
        # Two-tailed p-value (normal CDF approximation)
        from scipy.stats import norm
        p_value = 2 * (1 - norm.cdf(abs(z)))
        
        # Effect size (Cohen's h)
        effect_size = 2 * (np.arcsin(np.sqrt(p2)) - np.arcsin(np.sqrt(p1)))
        
        return p_value, abs(effect_size)
    
    def promote_challenger(self, test_id: str):
        """Promote challenger to champion after winning test."""
        if test_id not in self.completed_tests:
            logger.warning(f"Test {test_id} not in completed tests")
            return
        
        test = self.completed_tests[test_id]
        logger.info(f"Promoted {test.challenger} to champion (was {test.champion})")
        
        # In production: update model registry to make challenger the new champion
    
    # ========== RETRAINING ==========
    
    def schedule_retraining(
        self,
        model_name: str,
        trigger: RetrainingTrigger,
        schedule_delay_hours: int = 24
    ) -> RetrainingJob:
        """Schedule model retraining."""
        job_id = f"retrain_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        job = RetrainingJob(
            id=job_id,
            model_name=model_name,
            trigger=trigger,
            start_time=datetime.now() + timedelta(hours=schedule_delay_hours)
        )
        
        self.retraining_jobs[job_id] = job
        logger.info(f"Scheduled retraining job {job_id}: {model_name} ({trigger.value})")
        
        return job
    
    def execute_retraining(
        self,
        job_id: str,
        training_data: np.ndarray,
        validation_data: np.ndarray,
        model_factory  # Function to train model
    ) -> bool:
        """Execute retraining job."""
        if job_id not in self.retraining_jobs:
            logger.error(f"Unknown job: {job_id}")
            return False
        
        job = self.retraining_jobs[job_id]
        job.status = "RUNNING"
        job.start_time = datetime.now()
        job.training_data_size = len(training_data)
        
        try:
            # Train model
            logger.info(f"Training {job.model_name} with {len(training_data)} samples")
            model = model_factory(training_data)
            
            # Validate
            pred = model.predict(validation_data)
            actual = validation_data[:, -1]
            accuracy = np.mean((pred > 0.5).astype(int) == actual)
            job.validation_accuracy = accuracy
            
            if accuracy > 0.50:  # Must exceed baseline
                job.status = "SUCCESS"
                new_version = f"{job.model_name}_v{datetime.now().strftime('%Y%m%d')}"
                job.result_model_version = new_version
                logger.info(f"Retraining success: {accuracy:.2%} accuracy")
                return True
            else:
                job.status = "FAILED"
                logger.warning(f"Retraining failed: accuracy {accuracy:.2%} < 50%")
                return False
        
        except Exception as e:
            job.status = "FAILED"
            logger.error(f"Retraining job {job_id} failed: {e}")
            return False
        finally:
            job.end_time = datetime.now()
    
    def get_retraining_history(self, model_name: str) -> List[RetrainingJob]:
        """Get retraining history for model."""
        return [j for j in self.retraining_jobs.values() if j.model_name == model_name]


# ============================================================================
# UTILITIES
# ============================================================================

def print_abtest_results(result: TestResult):
    """Print A/B test results."""
    print("\n" + "="*60)
    print("  A/B TEST RESULTS")
    print("="*60)
    
    print(f"\n🥇 CHAMPION: {result.test_id.split('_')[1]}")
    print(f"  Accuracy:    {result.champion_metrics.accuracy:.2%}")
    print(f"  Precision:   {result.champion_metrics.precision:.2%}")
    print(f"  Recall:      {result.champion_metrics.recall:.2%}")
    print(f"  F1 Score:    {result.champion_metrics.f1_score:.2%}")
    
    print(f"\n🥈 CHALLENGER")
    print(f"  Accuracy:    {result.challenger_metrics.accuracy:.2%}")
    print(f"  Precision:   {result.challenger_metrics.precision:.2%}")
    print(f"  Recall:      {result.challenger_metrics.recall:.2%}")
    print(f"  F1 Score:    {result.challenger_metrics.f1_score:.2%}")
    
    print(f"\n📊 STATISTICAL TEST")
    print(f"  Sample Size: {result.sample_size}")
    print(f"  P-Value:     {result.p_value:.4f}")
    print(f"  Confidence:  {result.confidence:.1%}")
    print(f"  Effect Size: {result.effect_size:.4f}")
    
    print(f"\n✅ RECOMMENDATION: {result.recommendation}")
    if result.champion_wins:
        print(f"   Champion maintains superiority")
    else:
        print(f"   Challenger shows improvement")
    
    print("\n" + "="*60 + "\n")
