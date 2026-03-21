#!/usr/bin/env python
"""Improved training with corrected parameters and debugging"""

import sys
from walk_forward_validation import run_walk_forward

print("\n" + "=" * 70)
print("IMPROVED MODEL TRAINING - DEBUG MODE")
print("=" * 70 + "\n")

print("[Issue] Previous training produced R² = -379.95 (worse than mean)")
print("[Root Cause] Likely combination of:")
print("  1. Stock price data has high noise, low predictability")
print("  2. LSTM model may be too complex for this task")
print("  3. 2-year window too short for training")
print("  4. Lookback window (60 days) not optimized")
print()

print("[Strategy] Try improved configuration:")
print()

configs = [
    {
        "name": "GRU_Smaller_Lite",
        "model_type": "gru",
        "epochs": 100,
        "period": "5y",  # More data
        "lookback": 20,  # Shorter lookback
        "description": "GRU (simpler), 5-year data, shorter lookback"
    },
    {
        "name": "LSTM_Extended",
        "model_type": "lstm",
        "epochs": 100,
        "period": "5y",
        "lookback": 30,
        "description": "LSTM, 5-year data (3x more training samples)"
    }
]

for i, config in enumerate(configs, 1):
    print(f"\n[Option {i}] {config['name']}")
    print(f"  Model: {config['model_type']}")
    print(f"  Epochs: {config['epochs']}")
    print(f"  Period: {config['period']}")
    print(f"  Lookback: {config['lookback']}")
    print(f"  Reason: {config['description']}")

print("\n" + "=" * 70)
print("RECOMMENDATION")
print("=" * 70)
print()
print("Try Option 1: GRU_Smaller_Lite")
print()
print("Reasons:")
print("  ✓ GRU has FEWER parameters than LSTM (simpler = less overfitting)")
print("  ✓ 5-year data = 1,250 trading days (2.5x more samples)")
print("  ✓ Lookback=20 means simpler patterns, easier to learn")
print("  ✓ 100 epochs with patience=15 may find better local minimum")
print()
print("Execute:")
print("  python walk_forward_validation.py \\")
print("    --ticker AAPL \\")
print("    --model-type gru \\")
print("    --epochs 100 \\")
print("    --period 5y \\")
print("    --lookback 20")
print()
print("=" * 70)
print()

print("[Note] If this also fails, consider:")
print("  • Switch to GRU (12K parameters vs 214K for LSTM)")
print("  • Use ensemble predictions (combine multiple models)")
print("  • Focus on signal generation vs price prediction")
print("  • Use returns-based model instead of price-based")
print()
