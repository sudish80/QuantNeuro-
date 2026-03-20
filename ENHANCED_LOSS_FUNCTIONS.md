# Enhanced Loss Functions for Neural Network Trading Model

## Overview

The loss function defines what the model optimizes during training. Standard regression losses (MSE/MAE) may not be ideal for financial forecasting. This document covers 12+ specialized loss variants tailored to trading-specific objectives.

**Location:** `production_hardening/loss_functions.py`  
**Usage:** Integrated into `trainer.py` via `get_loss_function(loss_name)` factory

---

## Loss Functions Catalog

### Classical Regression Losses

#### 1. **MSE** (Mean Squared Error)
```
L = (1/N) Σ (ŷ - y)²
```
- **When to use:** Baseline; strongly penalizes large errors
- **Pros:** Standard, smooth gradients, universally applicable
- **Cons:** Outliers (market gaps/gaps) can dominate training
- **Trading application:** Acceptable for smaller gaps; problematic in high-vol

#### 2. **MAE** (Mean Absolute Error)
```
L = (1/N) Σ |ŷ - y|
```
- **When to use:** Robust to outliers; more interpretable errors
- **Pros:** All errors weighted equally; less affected by extreme values
- **Cons:** Non-smooth at zero (gradient undefined)
- **Trading application:** Better than MSE for gap-prone markets; underweights precision near target

#### 3. **Huber**
```
L = { 0.5 * error² if |error| < δ
    { δ * (|error| - 0.5*δ) if |error| ≥ δ
```
- **When to use:** Balanced robustness to outliers + precision; industry standard
- **Pros:** Combines MSE efficiency (near zero), MAE robustness (large errors)
- **Cons:** Requires tuning δ parameter
- **Trading application:** Reliable all-purpose choice

#### 4. **RMSE** (Root Mean Squared Error)
```
L = √[(1/N) Σ (ŷ - y)²]
```
- **When to use:** Same as MSE, but output in price units
- **Pros:** Interpretable ("average error: $X"); easier to communicate to traders
- **Cons:** Same gradient behavior as MSE
- **Trading application:** Better for reporting; average error in dollars vs dollars²

---

### Robust-to-Outliers Losses

#### 5. **LogCosh** (Log-Hyperbolic Cosine)
```
L = log(cosh(ŷ - y))
```
- **When to use:** Market regime with occasional gaps/anomalies
- **Pros:** 
  - Smooth everywhere (differentiable in both derivatives)
  - Approximately |error| for large errors (robust)
  - Quadratic near zero (efficient learning)
- **Cons:** Slightly more compute-intensive
- **Trading application:** Premium choice for volatile markets with rare outliers; prevents training collapse during flash crashes

---

### Asymmetric Losses (Direction-Aware)

#### 6. **Quantile Loss**
```
L = Σ max(q * error, (q - 1) * error)
where error = y - ŷ
```
- **Quantile q = 0.5:** Median (equivalent to MAE)
- **Quantile q = 0.9:** Upper bound (penalizes underestimation)
- **Quantile q = 0.1:** Lower bound (penalizes overestimation)

**When to use:** Predict confidence intervals instead of point estimates

**Use cases:**
- **Long positions:** Use q=0.9 to predict upside; don't miss gains
- **Short positions:** Use q=0.1 to predict downside; don't miss loss protection
- **Risk management:** Train three models (q=0.1, 0.5, 0.9) for risk bounds

**Pros:**
- Asymmetric; can cost different for missing up vs down
- Predicts percentiles, not just expected value
- Enables quantile-based risk assessment

**Example:**
```python
# Predict 90th percentile (upper bound for long)
model_upper = train(loss="quantile", quantile=0.9)  # Penalizes underestimation
# Predict 10th percentile (lower bound for short)
model_lower = train(loss="quantile", quantile=0.1)  # Penalizes overestimation
```

#### 7. **Pinball Loss** (Same as Quantile; Different Formulation)
```
L = Σ { q * error if error > 0
      { (1 - q) * |error| if error ≤ 0
```
- **Interpretation:** Asymmetric penalty for over/underestimation
- **q = 0.75:** Penalize underestimation 3x more than overestimation
- **Trading:** If long signal is more valuable than short signal

#### 8. **Directional-Weighted Loss**
```
L = (1 - α) * L_direction + α * L_magnitude
```
- **When to use:** Direction (buy/sell) matters more than exact price
- **α parameter:**
  - α = 0.1 (90% direction): Focus on getting signal right; magnitude secondary
  - α = 0.3 (70% direction): Balanced
  - α = 0.5 (50%): Equal weight to direction and magnitude

**Trading motivation:** Wrong signal = capital loss; magnitude off = execution loss  
In most cases, direction is more critical.

**Example:**
```python
# Train with 80% emphasis on direction correctness
model = train(loss="direction_weighted", alpha=0.2)
```

---

### Percentage-Based Loss

#### 9. **SMAPE** (Symmetric Mean Absolute Percentage Error)
```
L = (1/N) Σ 2|ŷ - y| / (|ŷ| + |y|)
```
- **When to use:** Return/percentage prediction (not absolute price)
- **Pros:** 
  - Scale-independent; 1% error = 1% error regardless of price level
  - Useful for multi-asset portfolios (BTC vs penny stocks)
  - Normalized: loss in [0, 1]
- **Cons:** Undefined when both pred and target are near zero
- **Trading application:** If you care about % returns rather than absolute dollars

**Example:**
```python
# For crypto (prices vary from $10 to $50k)
model = train(loss="smape")  # 5% error is same cost across price scales
```

---

### Advanced/Composite Losses

#### 10. **HuberLogCombined**
```
L = (1 - β) * L_huber + β * L_logcosh
```
- **When to use:** Need robustness without sacrificing stability
- **Parameters:**
  - β = 0.5: Equal balance (default)
  - β = 0.3: Prioritize Huber-style robustness
  - β = 0.7: Prioritize log-cosh smoothness

**Trading advantage:** Combines two complementary robustness strategies

#### 11. **AdaptiveWeighted Loss**
```
L = Σ weights * (ŷ - y)²
where weights = 1 + |ŷ - y|
```
- **When to use:** Model struggles with specific price ranges (e.g., very high/low volatility periods)
- **Effect:** Larger errors get higher gradients; model focuses on hardest samples
- **Pros:** Automatically focuses on edge cases
- **Cons:** Can overfit to outliers if not balanced with regularization

**Trading application:** If morning gaps are systematically mispredicted, adaptive weighting helps focus on improving that regime.

#### 12. **ReturnVolatilityLoss** (Regime-Aware)
```
weights = 1 / (realized_volatility + ε)
L = Σ weights * (ŷ - y)²
```
- **When to use:** Market volatility varies significantly over time
- **Effect:** 
  - High-vol periods: Larger errors accepted as "market noise"
  - Low-vol periods: Tight predictions required
  
**Trading advantage:** Prevents model from overconfidently trading in quiet periods.

---

## Choosing a Loss Function: Decision Tree

```
START: What's your primary objective?

├─ EXACT PRICE PREDICTION?
│  ├─ Yes, and data is clean (no gaps)      → MSE or RMSE
│  ├─ Yes, but data has occasional outliers → Huber or LogCosh
│  └─ Yes, and focus on magnitude equally   → MAE
│
├─ DIRECTIONAL SIGNAL (Buy/Sell)?
│  ├─ No: direction and magnitude + equal   → MSE, MAE, Huber
│  └─ Yes: direction >> magnitude           → DirectionWeighted (α=0.1-0.3)
│
├─ ASYMMETRIC COSTS (miss-up vs miss-down)?
│  ├─ Long only (miss upside = worse)       → Quantile (q=0.9)
│  ├─ Short only (miss downside = worse)    → Quantile (q=0.1)
│  ├─ Dynamic (depends on signal)           → Pinball + ensemble
│  └─ Equal cost                            → Symmetric (MSE, MAE, Huber)
│
├─ RETURN/PERCENTAGE PREDICTION (not dollar)?
│  └─ Yes, across different asset scales    → SMAPE
│
├─ DEALING WITH VOLATILITY CLUSTERS?
│  ├─ High vol = slack, low vol = tight     → ReturnVolatilityLoss
│  └─ No special regimes                    → Standard loss
│
└─ OUTLIERS & STABILITY?
   ├─ Many outliers, need robustness        → LogCosh or HuberLogCombined
   ├─ Mix of robustness + efficiency        → Huber (δ=1.0)
   └─ Clean data, focus on fit              → MSE or MAE
```

---

## Implementation

### Using in Training

```python
from trainer import train_model

# Simple
history = train_model(
    model=model,
    X_train=X_train, y_train=y_train,
    X_test=X_test, y_test=y_test,
    loss_name="logcosh",  # Enhanced loss
    device=device
)

# With parameters
history = train_model(
    model=model,
    X_train=X_train, y_train=y_train,
    X_test=X_test, y_test=y_test,
    loss_name="direction_weighted",  # 70% direction emphasis
    loss_alpha=0.3,
    device=device
)
```

### Creating Custom Loss

```python
from production_hardening.loss_functions import get_loss_function
import torch.nn as nn

# Instantiate via factory
criterion = get_loss_function("quantile", quantile=0.95)

# Or use directly
from production_hardening.loss_functions import QuantileLoss
criterion = QuantileLoss(quantile=0.95)

# Train step
loss = criterion(predictions, targets)
loss.backward()
```

---

## Empirical Recommendations

### By Market Condition

| Condition | Recommended Loss | Reason |
|-----------|------------------|--------|
| Smooth market, clean data | MSE, RMSE | Efficient learning; well-behaved gradients |
| Volatile market with gaps | LogCosh, Huber | Robustness to outliers; stable convergence |
| Directional signals (LSTM) | DirectionWeighted | Signal correctness > magnitude |
| Risk bounds / confidence intervals | Quantile ensemble | Predict upper/lower bounds |
| Multi-asset portfolio | SMAPE | Scale-independent; fair across assets |
| Intraday trading | ReturnVolatility | Adapt to vol clustering |
| Production (mixed conditions) | HuberLogCombined | Balanced, proven robustness |

### By Model Type

| Model | Loss | Rationale |
|-------|------|-----------|
| Feedforward (fully connected) | Huber, MSE | Dense gradients; outliers less likely |
| LSTM (sequence) | DirectionWeighted, LogCosh | Often predicts directions; focus on signal |
| Hybrid LSTM+FC | HuberLogCombined | Temporal + static; need robustness |
| Ensemble (3+ models) | Quantile (0.1, 0.5, 0.9) | Predict uncertainty ranges |

---

## Testing & Validation

All loss functions are unit-tested in `tests/test_loss_functions.py`:

Covers:
- ✅ Correct computation
- ✅ Gradient flow (backpropagation)
- ✅ Numerical stability (no NaNs/Infs)
- ✅ Domain-specific behavior (quantile asymmetry, etc.)

Run tests:
```bash
python -m unittest tests.test_loss_functions -v
```

**Current Results:** 15 tests, all passing ✅

---

## References

1. **Quantile Regression:**  
   Koenker & Bassett (1978). "Regression Quantiles"

2. **Huber Loss (Robust Statistics):**  
   Huber, P. J. (1964). "Robust Estimation of a Location Parameter"

3. **Log-Cosh (Smooth Robustness):**  
   Chen & Guestrin (2016). "XGBoost: A Scalable Tree Boosting System"

4. **Time Series Volatility (Regime-Aware):**  
   Bollerslev (1986). "Generalized Autoregressive Conditional Heteroskedasticity (GARCH)"

---

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| Loss NaN after few epochs | Large gradients during initialization | Start with Huber/LogCosh; increase δ parameter |
| Model overfits to outliers | Wrong loss focus | Switch to LogCosh or SMAPE |
| Validation loss stagnates | Loss unsuitable for problem | Try ensemble: train 3 models with different losses |
| Slow convergence | Gradients too small | Use MSE instead of MAE; or reduce patience in early stopping |
| Model predicts constant value | Loss minimum at mean | Add regularization; or use AdaptiveWeighted |

---

## Summary

Use the **factory function** `get_loss_function(loss_name)` in `trainer.py` to select losses:

```python
# Available losses (12 total)
"mse", "mae", "huber", "rmse", "logcosh", 
"quantile", "pinball", "smape", "direction_weighted",
"huber_logcosh", "adaptive_weighted", "return_volatility"
```

**Recommended starting points:**
- **Quick tests:** MSE or Huber
- **Production trading:** LogCosh or HuberLogCombined
- **Directional signals:** DirectionWeighted (α=0.3)
- **Risk bounds:** Quantile ensemble (0.1, 0.5, 0.9)

---

**Last Updated:** March 20, 2026  
**Status:** Production-ready; all tests passing
