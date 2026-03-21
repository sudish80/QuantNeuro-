#!/usr/bin/env python
"""Quick model training test with synthetic data"""

import numpy as np
import torch
from models import build_model
from trainer import train_model

def main():
    print("=" * 70)
    print("MODEL TRAINING TEST")
    print("=" * 70)
    
    # Create tiny synthetic data for testing
    np.random.seed(42)
    torch.manual_seed(42)
    
    n_samples = 200
    n_features = 10
    X_train = np.random.randn(n_samples, n_features).astype(np.float32)
    y_train = np.random.randn(n_samples, 1).astype(np.float32)
    X_test = np.random.randn(50, n_features).astype(np.float32)
    y_test = np.random.randn(50, 1).astype(np.float32)
    
    device = torch.device('cpu')
    model = build_model('lstm', n_features, 1, hidden_size=32, num_layers=2)
    
    print("\n[Starting model training (synthetic data test)...]")
    print(f"  Model: LSTM")
    print(f"  Samples: {n_samples}")
    print(f"  Features: {n_features}")
    print(f"  Epochs: 10")
    print()
    
    history = train_model(
        model=model,
        X_train=X_train,
        y_train=y_train,
        X_test=X_test,
        y_test=y_test,
        device=device,
        epochs=10,
        batch_size=32,
        learning_rate=1e-3,
        patience=5,
        loss_name='mse'
    )
    
    print("\n" + "=" * 70)
    print("✅ TRAINING COMPLETED!")
    print("=" * 70)
    print(f"  Final train loss: {history['train_losses'][-1]:.6f}")
    print(f"  Final test loss: {history['test_losses'][-1]:.6f}")
    print(f"  Best epoch: {history['best_epoch']}")
    print()

if __name__ == "__main__":
    main()
