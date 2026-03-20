"""
Example usage of enhanced loss functions for different trading scenarios.

Demonstrates:
1. Standard regression (exact price prediction)
2. Directional signals (buy/sell)
3. Risk-aware prediction (confidence bounds)
4. Volatility-adjusted learning
"""

import torch
import torch.nn as nn
from production_hardening.loss_functions import get_loss_function


def example_1_exact_price_prediction():
    """Scenario: Predict closing price exactly."""
    print("=" * 60)
    print("EXAMPLE 1: Exact Price Prediction")
    print("=" * 60)
    
    # Mock data
    predictions = torch.tensor([101.0, 99.5, 102.0, 98.0, 100.5])
    targets = torch.tensor([100.0, 100.0, 100.0, 100.0, 100.0])  # All at 100
    
    # Compare losses
    for loss_name in ["mse", "mae", "huber", "logcosh", "rmse"]:
        criterion = get_loss_function(loss_name)
        loss = criterion(predictions, targets).item()
        print(f"  {loss_name:15s}: {loss:10.4f}")
    
    print("\n  ⟹ Recommendation: RMSE for interpretability\n")


def example_2_directional_signal():
    """Scenario: Predict buy/sell signal (direction matters most)."""
    print("=" * 60)
    print("EXAMPLE 2: Directional Signals (Buy/Sell)")
    print("=" * 60)
    
    baseline = 100.0
    
    # Case 1: Wrong direction (predicts up, goes down)
    pred_wrong_dir = torch.tensor([105.0])  # Wrong: predicts UP
    targ_wrong_dir = torch.tensor([95.0])   # True: DOWN
    
    # Case 2: Correct direction (predicts down, goes down)
    pred_right_dir = torch.tensor([95.0])   # Correct: predicts DOWN
    targ_right_dir = torch.tensor([95.0])   # True: DOWN
    
    print("  Case 1 (Wrong Direction):")
    print(f"    Prediction: {pred_wrong_dir.item():6.1f} (↑), Actual: {targ_wrong_dir.item():6.1f} (↓)")
    
    print("\n  Case 2 (Correct Direction):")
    print(f"    Prediction: {pred_right_dir.item():6.1f} (↓), Actual: {targ_right_dir.item():6.1f} (↓)")
    
    print("\n  Loss Comparison:")
    
    for alpha in [0.1, 0.3, 0.5]:
        criterion = get_loss_function("direction_weighted", alpha=alpha)
        loss_wrong = criterion(pred_wrong_dir, targ_wrong_dir).item()
        loss_right = criterion(pred_right_dir, targ_right_dir).item()
        
        print(f"\n    α={alpha} (direction emphasis: {int((1-alpha)*100)}%):")
        print(f"      Wrong direction loss: {loss_wrong:10.4f}")
        print(f"      Right direction loss: {loss_right:10.4f}")
        print(f"      Penalty ratio: {loss_wrong/max(loss_right, 1e-8):6.2f}x")
    
    print("\n  ⟹ Recommendation: DirectionWeighted(α=0.2-0.3)\n")


def example_3_confidence_bounds():
    """Scenario: Predict upper/lower bounds for risk management."""
    print("=" * 60)
    print("EXAMPLE 3: Risk-Aware Bounds (Quantile Ensemble)")
    print("=" * 60)
    
    # Train three models with different quantiles
    prices = torch.tensor([95.0, 102.0, 98.0, 105.0, 99.0])
    targets = torch.tensor([100.0, 100.0, 100.0, 100.0, 100.0])
    
    print("  Training ensemble with quantile losses:")
    print("\n  Quantile 0.10 (lower bound - pessimistic):")
    loss_lower = get_loss_function("quantile", quantile=0.1)
    print(f"    Loss: {loss_lower(prices, targets).item():.4f}")
    print("    Purpose: Don't miss downside risk; penalizes overestimation")
    
    print("\n  Quantile 0.50 (median - balanced):")
    loss_median = get_loss_function("quantile", quantile=0.5)
    print(f"    Loss: {loss_median(prices, targets).item():.4f}")
    print("    Purpose: Expected price; minimize mean error")
    
    print("\n  Quantile 0.90 (upper bound - optimistic):")
    loss_upper = get_loss_function("quantile", quantile=0.9)
    print(f"    Loss: {loss_upper(prices, targets).item():.4f}")
    print("    Purpose: Don't miss upside; penalizes underestimation")
    
    print("\n  ⟹ Recommendation:")
    print("    - Use 3-model ensemble for risk bounds")
    print("    - Long positions → optimize q=0.9 (catch upside)")
    print("    - Short positions → optimize q=0.1 (catch downside)\n")


def example_4_volatility_regimes():
    """Scenario: Model learns different generalization in different market regimes."""
    print("=" * 60)
    print("EXAMPLE 4: Volatility-Aware Training")
    print("=" * 60)
    
    # Low volatility period (tight predictions expected)
    low_vol_pred = torch.tensor([100.1, 99.9, 100.05, 99.95])
    low_vol_targ = torch.tensor([100.0, 100.0, 100.0, 100.0])
    
    # High volatility period (larger moves OK)
    high_vol_pred = torch.tensor([110.0, 95.0, 105.0, 92.0])
    high_vol_targ = torch.tensor([100.0, 100.0, 100.0, 100.0])
    
    print("  Scenario: Same prediction errors, different volatility")
    print("\n  Low Volatility (tight market):")
    print(f"    MAE: {torch.nn.L1Loss()(low_vol_pred, low_vol_targ).item():.4f}")
    print("    Expectation: Small errors are 'failures'")
    
    print("\n  High Volatility (choppy market):")
    print(f"    MAE: {torch.nn.L1Loss()(high_vol_pred, high_vol_targ).item():.4f}")
    print("    Expectation: Medium errors are acceptable")
    
    print("\n  ⟹ With ReturnVolatilityLoss:")
    print("    - Penalizes high-vol period less heavily")
    print("    - Penalizes low-vol period more strictly")
    print("    - Adapts to market regime automatically\n")


def example_5_robustness_to_gaps():
    """Scenario: Market gaps/anomalies; need outlier-robust loss."""
    print("=" * 60)
    print("EXAMPLE 5: Outlier Robustness (Flash Crash)")
    print("=" * 60)
    
    # Normal predictions
    pred_normal = torch.tensor([100.5, 99.8, 100.2, 99.7, 100.1])
    targ_normal = torch.tensor([100.0, 100.0, 100.0, 100.0, 100.0])
    
    # One flash crash (outlier)
    pred_crash = torch.tensor([100.5, 99.8, 50.0, 99.7, 100.1])  # -50 gap
    targ_crash = torch.tensor([100.0, 100.0, 100.0, 100.0, 100.0])
    
    print("  Scenario: Model predicts normally, then flash crash (50-point gap)")
    print("\n  Normal predictions (clean dataset):")
    
    for loss_name in ["mse", "mae", "logcosh", "huber"]:
        criterion = get_loss_function(loss_name)
        loss = criterion(pred_normal, targ_normal).item()
        print(f"    {loss_name:10s}: {loss:10.4f}")
    
    print("\n  With flash crash (one 50-point outlier):")
    
    for loss_name in ["mse", "mae", "logcosh", "huber"]:
        criterion = get_loss_function(loss_name)
        loss = criterion(pred_crash, targ_crash).item()
        print(f"    {loss_name:10s}: {loss:10.4f}")
    
    print("\n  Impact of outlier:")
    mse_impact = (get_loss_function("mse")(pred_crash, targ_crash).item() / 
                  get_loss_function("mse")(pred_normal, targ_normal).item())
    logcosh_impact = (get_loss_function("logcosh")(pred_crash, targ_crash).item() / 
                      get_loss_function("logcosh")(pred_normal, targ_normal).item())
    
    print(f"    MSE multiplier:      {mse_impact:6.1f}x increase")
    print(f"    LogCosh multiplier:  {logcosh_impact:6.1f}x increase")
    
    print("\n  ⟹ Recommendation: LogCosh for outlier robustness\n")


def example_6_production_recommendation():
    """Show recommended loss selection for production."""
    print("=" * 60)
    print("EXAMPLE 6: Production Recommendation")
    print("=" * 60)
    
    scenarios = [
        ("Baseline (unknown)", "Huber"),
        ("Smooth, clean data", "MSE or RMSE"),
        ("Volatile with gaps", "LogCosh or HuberLogCombined"),
        ("Directional signals", "DirectionWeighted (α=0.2-0.3)"),
        ("Risk bounds needed", "Quantile ensemble (0.1, 0.5, 0.9)"),
        ("Multi-asset portfolio", "SMAPE"),
        ("Production (mixed)", "HuberLogCombined (balanced robustness)"),
    ]
    
    for scenario, recommendation in scenarios:
        print(f"  {scenario:30s} → {recommendation}")
    
    print("\n  Default for production trading:")
    print("    - Start: Huber(delta=1.0)")
    print("    - Scale up complexity: HuberLogCombined(beta=0.5)")
    print("    - With signals: DirectionWeighted(alpha=0.3)")
    print("    - For uncertainty: Quantile ensemble\n")


if __name__ == "__main__":
    example_1_exact_price_prediction()
    example_2_directional_signal()
    example_3_confidence_bounds()
    example_4_volatility_regimes()
    example_5_robustness_to_gaps()
    example_6_production_recommendation()
    
    print("=" * 60)
    print("For detailed documentation, see: ENHANCED_LOSS_FUNCTIONS.md")
    print("=" * 60)
