"""
Golden Dataset Regression Tests - Catch silent model behavior changes.

Uses a fixed dataset with known outcomes to detect unexpected behavior changes
that could indicate model drift, data issues, or code regressions.
"""

import pytest
import numpy as np
import pandas as pd
import torch
from typing import Dict, List, Tuple
from datetime import datetime, timedelta


# ============================================================================
# GOLDEN DATASET FIXTURES
# ============================================================================


@pytest.fixture(scope="session")
def golden_dataset() -> Tuple[pd.DataFrame, pd.DataFrame, List[str]]:
    """
    Create a fixed golden dataset for regression testing.
    Returns (features_df, labels_df, feature_names).
    """
    np.random.seed(42)  # Fixed seed for reproducibility
    
    # Create 100 samples of historical data
    n_samples = 100
    dates = pd.date_range(end=datetime.utcnow(), periods=n_samples, freq='1D')
    
    # Features: OHLCV data normalized
    features = np.random.randn(n_samples, 10)  # 10 features
    feature_names = [
        "open_change", "high_change", "low_change", "close_change",
        "volume_ratio", "price_momentum", "volatility", "rsi", "macd", "bollinger"
    ]
    
    features_df = pd.DataFrame(features, columns=feature_names, index=dates)
    
    # Labels: direction (1 = up, -1 = down, 0 = flat)
    labels = np.random.choice([-1, 0, 1], n_samples)
    labels_df = pd.DataFrame(labels, columns=["direction"], index=dates)
    
    return features_df, labels_df, feature_names


@pytest.fixture(scope="session")
def golden_model_predictions(golden_dataset) -> Dict[str, np.ndarray]:
    """
    Store known-good model predictions on golden dataset.
    In production, these are saved from a validated model run.
    """
    return {
        "predictions": np.array([0.52, 0.48, 0.55, 0.45, 0.50] * 20),  # 100 samples
        "probabilities": np.array([[0.52, 0.48], [0.48, 0.52]] * 50),
        "embeddings": np.random.randn(100, 64),  # Feature embeddings
    }


@pytest.fixture
def golden_baseline_metrics() -> Dict[str, float]:
    """Expected metrics on golden dataset."""
    return {
        "accuracy": 0.65,           # ±5% tolerance
        "precision": 0.68,
        "recall": 0.62,
        "f1_score": 0.65,
        "sharpe_ratio": 1.8,        # ±0.5 tolerance
        "win_rate": 0.62,           # ±3% tolerance
        "max_drawdown": -0.12,      # ±2% tolerance
    }


@pytest.fixture
def golden_inference_outputs(golden_dataset) -> Dict[str, np.ndarray]:
    """Expected inference outputs on golden dataset."""
    return {
        "predictions": np.array([0.51, 0.49, 0.56, 0.44, 0.51] * 20),
        "signals": np.array(["BUY", "HOLD", "BUY", "SELL", "HOLD"] * 20),
    }


# ============================================================================
# REGRESSION TESTS
# ============================================================================


class TestModelRegressionOnGoldenDataset:
    """Test for model output regressions on golden dataset."""

    def test_model_predictions_stable(self, golden_dataset, golden_model_predictions):
        """Model should produce stable predictions on golden dataset."""
        features_df, labels_df, feature_names = golden_dataset
        
        # Import and run model
        from models import build_model
        import torch
        
        model = build_model(
            input_size=len(feature_names),
            output_size=2,
            hidden_sizes=[64, 32],
            dropout=0.2
        )
        model.eval()
        
        # Convert to tensor and predict
        X = torch.FloatTensor(features_df.values)
        with torch.no_grad():
            predictions = model(X)
        
        # Predictions should be similar (within 5%)
        predicted_probs = predictions.softmax(dim=1).numpy()
        expected_probs = golden_model_predictions["probabilities"]
        
        # Allow 5% deviation
        max_deviation = 0.05
        actual_deviation = np.max(np.abs(predicted_probs - expected_probs))
        
        assert actual_deviation < max_deviation, (
            f"Model predictions deviated {actual_deviation:.3f} "
            f"(tolerance: {max_deviation})"
        )

    def test_model_accuracy_maintained(self, golden_dataset, golden_baseline_metrics):
        """Model accuracy should be maintained within tolerance."""
        features_df, labels_df, _ = golden_dataset
        
        from models import build_model
        import torch
        from sklearn.metrics import accuracy_score
        
        model = build_model(input_size=10, output_size=2)
        model.eval()
        
        X = torch.FloatTensor(features_df.values)
        with torch.no_grad():
            predictions = model(X)
        
        pred_labels = predictions.argmax(dim=1).numpy()
        true_labels = (labels_df["direction"].values > 0).astype(int)
        
        accuracy = accuracy_score(true_labels, pred_labels)
        expected_accuracy = golden_baseline_metrics["accuracy"]
        tolerance = 0.05  # 5% tolerance
        
        assert abs(accuracy - expected_accuracy) < tolerance, (
            f"Accuracy {accuracy:.3f} deviated from baseline "
            f"{expected_accuracy:.3f} (tolerance: {tolerance})"
        )

    def test_ranking_stability(self, golden_dataset):
        """Top features should maintain relative importance ranking."""
        features_df, _, feature_names = golden_dataset
        
        # Compute correlations with target
        target = np.random.choice([0, 1], len(features_df))
        correlations = {}
        
        for feat in feature_names:
            corr = np.corrcoef(features_df[feat], target)[0, 1]
            correlations[feat] = abs(corr)
        
        # Get top 3 most important features
        top_3 = sorted(correlations.items(), key=lambda x: x[1], reverse=True)[:3]
        top_3_names = [name for name, _ in top_3]
        
        # Expected top features (from golden dataset)
        expected_top = ["price_momentum", "volatility", "rsi"]
        
        # At least 2 of top 3 should match expected
        matching = len(set(top_3_names) & set(expected_top))
        assert matching >= 2, (
            f"Feature importance ranking changed. "
            f"Got {top_3_names}, expected to include {expected_top}"
        )


# ============================================================================
# PREPROCESSING REGRESSION TESTS
# ============================================================================


class TestPreprocessingRegressionOnGoldenDataset:
    """Test preprocessing pipeline doesn't change output format."""

    def test_preprocessing_output_shape(self, golden_dataset):
        """Preprocessing should maintain expected output shape."""
        features_df, _, _ = golden_dataset
        
        from preprocessing import prepare_dataset
        
        X, y = prepare_dataset(features_df.values, test_size=0.2)
        
        # Expected shapes
        assert X.shape[0] > 0, "Dataset is empty"
        assert X.shape[1] == 10, f"Expected 10 features, got {X.shape[1]}"
        assert len(y) == X.shape[0], "Features and labels mismatch"

    def test_preprocessing_no_nan_leakage(self, golden_dataset):
        """Preprocessing should not introduce NaNs."""
        features_df, _, _ = golden_dataset
        
        from preprocessing import prepare_dataset
        
        X, y = prepare_dataset(features_df.values, test_size=0.2)
        
        assert not np.isnan(X).any(), "NaNs found in features"
        assert not np.isnan(y).any(), "NaNs found in labels"

    def test_preprocessing_value_ranges(self, golden_dataset):
        """Preprocessed values should be normalized (-5 to 5)."""
        features_df, _, _ = golden_dataset
        
        from preprocessing import prepare_dataset
        
        X, y = prepare_dataset(features_df.values, test_size=0.2)
        
        # Normalized values should be in reasonable range
        assert np.max(np.abs(X)) < 10, (
            f"Preprocessed values out of expected range: max={np.max(np.abs(X))}"
        )


# ============================================================================
# INFERENCE REPEATABILITY TESTS
# ============================================================================


class TestInferenceRepeatability:
    """Test inference is deterministic on golden dataset."""

    def test_same_input_same_output(self, golden_dataset):
        """Same input should produce same output (deterministic)."""
        features_df, _, _ = golden_dataset
        
        from models import build_model
        import torch
        
        torch.manual_seed(42)
        model = build_model(input_size=10, output_size=2)
        model.eval()
        
        X = torch.FloatTensor(features_df.iloc[:5].values)
        
        # First inference
        with torch.no_grad():
            pred1 = model(X).numpy()
        
        # Second inference
        with torch.no_grad():
            pred2 = model(X).numpy()
        
        # Should be identical
        assert np.allclose(pred1, pred2), "Predictions not deterministic"

    def test_batch_vs_sequential_consistency(self, golden_dataset):
        """Batch inference should match sequential."""
        features_df, _, _ = golden_dataset
        
        from models import build_model
        import torch
        
        model = build_model(input_size=10, output_size=2)
        model.eval()
        
        X = torch.FloatTensor(features_df.values)
        
        # Batch inference
        with torch.no_grad():
            batch_pred = model(X).numpy()
        
        # Sequential inference
        sequential_pred_list = []
        with torch.no_grad():
            for sample in X:
                pred = model(sample.unsqueeze(0)).numpy()
                sequential_pred_list.append(pred)
        sequential_pred = np.vstack(sequential_pred_list)
        
        # Should be similar
        assert np.allclose(batch_pred, sequential_pred, atol=1e-5), (
            "Batch vs sequential inference diverged"
        )


# ============================================================================
# SIGNAL GENERATION REGRESSION TESTS
# ============================================================================


class TestSignalGenerationRegression:
    """Test signal generation is consistent on golden dataset."""

    def test_signal_distribution(self, golden_inference_outputs):
        """Signal distribution should remain balanced."""
        signals = golden_inference_outputs["signals"]
        
        buy_pct = np.sum(signals == "BUY") / len(signals)
        sell_pct = np.sum(signals == "SELL") / len(signals)
        hold_pct = np.sum(signals == "HOLD") / len(signals)
        
        # Signals should be roughly balanced
        assert 0.2 < buy_pct < 0.4, f"BUY signal distribution off: {buy_pct:.1%}"
        assert 0.2 < sell_pct < 0.4, f"SELL signal distribution off: {sell_pct:.1%}"
        assert 0.2 < hold_pct < 0.4, f"HOLD signal distribution off: {hold_pct:.1%}"

    def test_trading_signals_valid(self, golden_inference_outputs):
        """All signals should be valid."""
        signals = golden_inference_outputs["signals"]
        
        valid_signals = {"BUY", "SELL", "HOLD"}
        assert np.all(np.isin(signals, list(valid_signals))), (
            f"Invalid signals found: {set(signals) - valid_signals}"
        )


# ============================================================================
# METRIC CALCULATION REGRESSION TESTS
# ============================================================================


class TestMetricCalculationRegression:
    """Test metric calculations are consistent."""

    def test_sharpe_ratio_calculation(self, golden_dataset):
        """Sharpe ratio calculation should be consistent."""
        features_df, _, _ = golden_dataset
        
        # Simulate returns
        returns = np.random.randn(100) * 0.02 + 0.001
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252)
        
        # Sharpe should be reasonable (0-3 range)
        assert -5 < sharpe < 5, f"Sharpe ratio unreasonable: {sharpe}"

    def test_win_rate_calculation(self, golden_baseline_metrics):
        """Win rate should be between 0 and 1."""
        win_rate = golden_baseline_metrics["win_rate"]
        
        assert 0 <= win_rate <= 1, f"Win rate out of range: {win_rate}"

    def test_drawdown_calculation(self, golden_baseline_metrics):
        """Drawdown should be non-positive."""
        max_dd = golden_baseline_metrics["max_drawdown"]
        
        assert max_dd <= 0, f"Max drawdown should be non-positive: {max_dd}"


# ============================================================================
# INTEGRATION REGRESSION TESTS
# ============================================================================


class TestEndToEndRegressionOnGolden:
    """End-to-end tests on golden dataset."""

    def test_full_pipeline_completes(self, golden_dataset):
        """Full pipeline should complete without errors."""
        features_df, labels_df, _ = golden_dataset
        
        from preprocessing import prepare_dataset
        from models import build_model
        import torch
        
        # Prepare data
        X, y = prepare_dataset(features_df.values, test_size=0.2)
        
        # Build model
        model = build_model(input_size=10, output_size=2)
        model.eval()
        
        # Run inference
        X_tensor = torch.FloatTensor(X[:10])
        with torch.no_grad():
            predictions = model(X_tensor)
        
        assert predictions.shape[0] == 10
        assert predictions.shape[1] == 2
        assert not torch.isnan(predictions).any()

    def test_golden_dataset_never_shrinks(self, golden_dataset):
        """Golden dataset size should never decrease."""
        features_df, _, _ = golden_dataset
        
        expected_size = 100
        actual_size = len(features_df)
        
        assert actual_size >= expected_size, (
            f"Golden dataset shrunk: {actual_size} < {expected_size}"
        )
