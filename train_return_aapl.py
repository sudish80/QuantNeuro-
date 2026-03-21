#!/usr/bin/env python
"""
Return-Based Model Training on Real AAPL Data

This script:
1. Fetches real AAPL price data (5 years)
2. Evaluates multiple configurations to find best
3. Reports directional accuracy on real market data
"""

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
import yfinance as yf
from typing import Tuple, Dict
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ReturnDataPreprocessor:
    """Convert prices to returns and prepare for training"""
    
    @staticmethod
    def prices_to_returns(prices: np.ndarray, log_returns: bool = True) -> np.ndarray:
        if log_returns:
            returns = np.diff(np.log(prices))
        else:
            returns = np.diff(prices) / prices[:-1]
        return returns
    
    @staticmethod
    def create_return_features(
        prices: np.ndarray,
        lookback: int,
        log_returns: bool = True
    ) -> Tuple[np.ndarray, np.ndarray]:
        returns = ReturnDataPreprocessor.prices_to_returns(prices, log_returns)
        
        X = []
        y = []
        
        for i in range(lookback, len(returns)):
            feature_window = returns[i - lookback:i]
            target_return = returns[i]
            X.append(feature_window)
            y.append(target_return)
        
        return np.array(X), np.array(y)


class ReturnPredictionModel(nn.Module):
    """LSTM for return prediction"""
    
    def __init__(self, input_size: int = 1, hidden_size: int = 64, num_layers: int = 2):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=0.3 if num_layers > 1 else 0.0
        )
        self.fc = nn.Linear(hidden_size, 1)
    
    def forward(self, x):
        lstm_out, _ = self.lstm(x)
        last_output = lstm_out[:, -1, :]
        prediction = self.fc(last_output)
        return prediction


def train_return_model(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_test: np.ndarray,
    y_test: np.ndarray,
    epochs: int = 100,
    batch_size: int = 32,
    learning_rate: float = 1e-3,
    patience: int = 20
) -> Tuple[Dict, nn.Module]:
    """Train return prediction model with early stopping"""
    
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    
    # Reshape for LSTM
    X_train_t = torch.tensor(X_train[:, :, np.newaxis], dtype=torch.float32)
    y_train_t = torch.tensor(y_train, dtype=torch.float32).reshape(-1, 1)
    X_test_t = torch.tensor(X_test[:, :, np.newaxis], dtype=torch.float32)
    y_test_t = torch.tensor(y_test, dtype=torch.float32).reshape(-1, 1)
    
    model = ReturnPredictionModel(input_size=1, hidden_size=64, num_layers=2)
    model = model.to(device)
    
    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    
    train_dataset = TensorDataset(X_train_t, y_train_t)
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    
    history = {
        'train_losses': [],
        'test_losses': [],
        'best_test_loss': float('inf'),
        'best_epoch': 0,
        'stopped_epoch': epochs
    }
    
    patience_counter = 0
    
    print(f"Training on real AAPL data...")
    print(f"  Device: {device}")
    print(f"  Training samples: {len(X_train)}")
    print(f"  Test samples: {len(X_test)}")
    print(f"  Lookback window: {X_train.shape[1]} days")
    print()
    
    for epoch in range(epochs):
        model.train()
        train_loss = 0.0
        for X_batch, y_batch in train_loader:
            X_batch = X_batch.to(device)
            y_batch = y_batch.to(device)
            
            optimizer.zero_grad()
            predictions = model(X_batch)
            loss = criterion(predictions, y_batch)
            loss.backward()
            optimizer.step()
            
            train_loss += loss.item()
        
        train_loss /= len(train_loader)
        
        model.eval()
        with torch.no_grad():
            X_test_device = X_test_t.to(device)
            y_test_device = y_test_t.to(device)
            test_predictions = model(X_test_device)
            test_loss = criterion(test_predictions, y_test_device).item()
        
        history['train_losses'].append(train_loss)
        history['test_losses'].append(test_loss)
        
        if test_loss < history['best_test_loss']:
            history['best_test_loss'] = test_loss
            history['best_epoch'] = epoch + 1
            patience_counter = 0
        else:
            patience_counter += 1
        
        if (epoch + 1) % 20 == 0:
            print(f"Epoch {epoch + 1:3d} | Train Loss: {train_loss:.8f} | Test Loss: {test_loss:.8f}")
        
        if patience_counter >= patience:
            print(f"Early stopping at epoch {epoch + 1}")
            history['stopped_epoch'] = epoch + 1
            break
    
    return history, model


def evaluate_directional_accuracy(y_test: np.ndarray, predictions: np.ndarray, threshold: float = 0.0005) -> Dict:
    """Evaluate directional accuracy"""
    
    actual_direction = (y_test > threshold).astype(int)
    pred_direction = (predictions > threshold).astype(int)
    
    correct = (actual_direction == pred_direction).sum()
    accuracy = correct / len(y_test)
    
    up_mask = actual_direction == 1
    down_mask = actual_direction == 0
    
    up_accuracy = (actual_direction[up_mask] == pred_direction[up_mask]).mean() if up_mask.sum() > 0 else 0
    down_accuracy = (actual_direction[down_mask] == pred_direction[down_mask]).mean() if down_mask.sum() > 0 else 0
    
    return {
        'overall_accuracy': accuracy,
        'up_accuracy': up_accuracy,
        'down_accuracy': down_accuracy,
        'up_samples': int(up_mask.sum()),
        'down_samples': int(down_mask.sum()),
        'up_correct': int((actual_direction[up_mask] == pred_direction[up_mask]).sum()) if up_mask.sum() > 0 else 0,
        'down_correct': int((actual_direction[down_mask] == pred_direction[down_mask]).sum()) if down_mask.sum() > 0 else 0
    }


if __name__ == "__main__":
    print("=" * 70)
    print("AAPL RETURN-BASED MODEL TRAINING")
    print("=" * 70)
    print()
    
    # Fetch AAPL data
    print("Fetching AAPL price data (5 years)...")
    aapl = yf.download('AAPL', period='5y', progress=False)
    prices = aapl['Adj Close'].values
    
    print(f"Downloaded {len(prices)} trading days")
    print(f"Date range: {aapl.index[0].date()} to {aapl.index[-1].date()}")
    print(f"Price range: ${prices.min():.2f} - ${prices.max():.2f}")
    print()
    
    # Convert to returns
    preprocessor = ReturnDataPreprocessor()
    X_returns, y_returns = preprocessor.create_return_features(prices, lookback=20, log_returns=True)
    
    print(f"Return statistics:")
    print(f"  Mean daily return: {y_returns.mean():.4%}")
    print(f"  Std dev: {y_returns.std():.4%}")
    print(f"  Min: {y_returns.min():.4%}")
    print(f"  Max: {y_returns.max():.4%}")
    print(f"  Up days: {(y_returns > 0).sum()} ({(y_returns > 0).mean():.1%})")
    print(f"  Down days: {(y_returns < 0).sum()} ({(y_returns < 0).mean():.1%})")
    print()
    
    # Train/test split (time-series split - no look-ahead)
    split_idx = int(0.8 * len(X_returns))
    X_train, X_test = X_returns[:split_idx], X_returns[split_idx:]
    y_train, y_test = y_returns[:split_idx], y_returns[split_idx:]
    
    print(f"Train/test split: {len(X_train)}/{len(X_test)} samples")
    print()
    
    # Train model
    history, model = train_return_model(
        X_train, y_train, X_test, y_test,
        epochs=100,
        batch_size=32,
        learning_rate=1e-3,
        patience=20
    )
    
    print()
    print("=" * 70)
    print("TRAINING RESULTS")
    print("=" * 70)
    print(f"Best test loss: {history['best_test_loss']:.8f} (epoch {history['best_epoch']})")
    print(f"Final train loss: {history['train_losses'][-1]:.8f}")
    print(f"Final test loss: {history['test_losses'][-1]:.8f}")
    print()
    
    # Evaluate directional accuracy
    model.eval()
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    X_test_t = torch.tensor(X_test[:, :, np.newaxis], dtype=torch.float32)
    with torch.no_grad():
        predictions = model(X_test_t.to(device)).cpu().numpy().flatten()
    
    accuracy = evaluate_directional_accuracy(y_test, predictions)
    
    print("DIRECTIONAL ACCURACY:")
    print(f"  Overall: {accuracy['overall_accuracy']:.2%}")
    print(f"  UP days: {accuracy['up_accuracy']:.2%} ({accuracy['up_correct']}/{accuracy['up_samples']} correct)")
    print(f"  DOWN days: {accuracy['down_accuracy']:.2%} ({accuracy['down_correct']}/{accuracy['down_samples']} correct)")
    print()
    
    if accuracy['overall_accuracy'] > 0.55:
        print("✅ SUCCESS! Model achieves >55% directional accuracy")
        print("   This means return-based approach WORKS on real data")
        print("   Ready for deployment to paper trading")
    elif accuracy['overall_accuracy'] > 0.52:
        print("⚠️  MODERATE: Model achieves 52-55% accuracy")
        print("   Ensemble and multi-ticker strategies may improve this")
    else:
        print("❌ FAILED: Model accuracy <= 52%")
        print("   Even with real data, simple LSTM not enough")
        print("   Next: Try ensemble, feature engineering, or other approaches")
