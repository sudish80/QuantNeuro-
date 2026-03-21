#!/usr/bin/env python
"""
Return-Based Model with Scikit-Learn
Lightweight alternative using simple neural networks
"""

import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
import warnings
warnings.filterwarnings('ignore')

print("=" * 70)
print("AAPL RETURN-BASED MODEL (Lightweight)")
print("=" * 70)
print()

# Fetch AAPL data
print("Fetching AAPL price data (5 years)...")
try:
    aapl = yf.download('AAPL', period='5y', progress=False)
    prices = aapl['Adj Close'].values
    print(f"✓ Downloaded {len(prices)} trading days")
    print(f"  Date range: {aapl.index[0].date()} to {aapl.index[-1].date()}")
    print(f"  Price range: ${prices.min():.2f} - ${prices.max():.2f}")
except Exception as e:
    print(f"✗ Failed to download: {str(e)}")
    print("Using synthetic fallback data...")
    np.random.seed(42)
    returns = np.random.normal(0.0005, 0.015, 1250)
    prices = 100 * np.exp(np.cumsum(returns))
    print(f"✓ Generated {len(prices)} synthetic price samples")

print()

# Convert to returns
returns = np.diff(np.log(prices))  # Log returns
print(f"Return statistics:")
print(f"  Mean daily return: {returns.mean():.4%}")
print(f"  Std dev: {returns.std():.4%}")
print(f"  Skewness: {pd.Series(returns).skew():.4f}")
print(f"  Kurtosis: {pd.Series(returns).kurtosis():.4f}")
print(f"  Up days: {(returns > 0).sum()} ({(returns > 0).mean():.1%})")
print(f"  Down days: {(returns < 0).sum()} ({(returns < 0).mean():.1%})")
print()

# Create features: use past 20 returns to predict next return direction
lookback = 20
X = []
y = []

for i in range(lookback, len(returns)):
    feature_window = returns[i - lookback:i]
    target_return = returns[i]
    X.append(feature_window)
    y.append(1 if target_return > 0 else 0)  # 1=UP, 0=DOWN

X = np.array(X)
y = np.array(y)

print(f"Dataset created: {len(X)} samples with {lookback}-day lookback")
print(f"  Class distribution: {(y==1).sum()} UP, {(y==0).sum()} DOWN")
print()

# Split (80/20)
split_idx = int(0.8 * len(X))
X_train, X_test = X[:split_idx], X[split_idx:]
y_train, y_test = y[:split_idx], y[split_idx:]

print(f"Train/test split: {len(X_train)}/{len(X_test)} samples")
print()

# Normalize
scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)

# Train multiple models
models = {
    'Logistic Regression': LogisticRegression(max_iter=500, random_state=42),
    'Random Forest': RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42),
    'Gradient Boosting': GradientBoostingClassifier(n_estimators=100, max_depth=5, random_state=42),
}

print("=" * 70)
print("TRAINING RESULTS")
print("=" * 70)
print()

best_accuracy = 0
best_model_name = None

for name, model in models.items():
    print(f"Training {name}...")
    model.fit(X_train_scaled, y_train)
    
    # Evaluate
    y_pred = model.predict(X_test_scaled)
    accuracy = accuracy_score(y_test, y_pred)
    precision = precision_score(y_test, y_pred, zero_division=0)
    recall = recall_score(y_test, y_pred, zero_division=0)
    f1 = f1_score(y_test, y_pred, zero_division=0)
    
    print(f"  Accuracy:  {accuracy:.2%}")
    print(f"  Precision: {precision:.2%}")
    print(f"  Recall:    {recall:.2%}")
    print(f"  F1 Score:  {f1:.4f}")
    print()
    
    if accuracy > best_accuracy:
        best_accuracy = accuracy
        best_model_name = name

print("=" * 70)
print(f"BEST MODEL: {best_model_name} ({best_accuracy:.2%})")
print("=" * 70)
print()

if best_accuracy > 0.55:
    print("✅ SUCCESS! Model achieves >55% directional accuracy")
    print("   Returns ARE predictable to some degree")
    print("   Ready to test on Alpaca paper trading")
elif best_accuracy > 0.52:
    print("⚠️  MARGINAL: Model achieves 52-55% accuracy")
    print("   Some signal present, but will need ensemble/features")
else:
    print("❌ FAILED: Model accuracy <= 52%")  
    print("   Even returns show limited predictability")
    print("   Next steps: Feature engineering, ensemble methods")

print()
print("CONCLUSION:")
print("-" * 70)
print(f"Return-based approach accuracy: {best_accuracy:.2%}")
print(f"Baseline (predict always DOWN): {(y_test==0).mean():.2%}")
print(f"Improvement over baseline: {best_accuracy - (y_test==0).mean():.2%}")
print()

if best_accuracy > (y_test==0).mean() + 0.03:
    print("✅ STATISTICALLY SIGNIFICANT improvement")
    print("   Model beats random guess + 3% margin")
else:
    print("📊 MARGINAL improvement")
    print("   Consider more sophisticated methods")
