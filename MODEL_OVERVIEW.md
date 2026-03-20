# Neural Network Trading Model Overview

## What this model does

This project builds neural networks that predict the next market price for stocks or crypto from historical OHLCV time-series data.

The system then converts predictions into trading signals (BUY, SELL, HOLD), applies basic risk management, and can run in paper mode or live mode execution flow.

---

## Main objective

The core prediction task is:

- Input: a sliding window of past market data and engineered indicators
- Output: the next closing price

Mathematically, the model learns a function:

f_theta(X_t-window:t) -> y_t+1

where:

- X is a sequence of multivariate features
- y is the next closing price
- theta are trainable model parameters

---

## End-to-end pipeline

### 1) Market data collection

Implemented in: data_fetcher.py

Supported sources:

- Yahoo Finance
- Binance REST API
- Alpha Vantage REST API

Collected fields include:

- Open
- High
- Low
- Close
- Volume
- Timestamp (index)

Output format:

timestamp | open | high | low | close | volume

### 2) Data cleaning

Also in: data_fetcher.py and preprocessing.py

Cleaning steps:

- Remove missing rows in required OHLCV fields
- Remove duplicate timestamps
- Normalize timestamp format to UTC where needed
- Sort by timestamp
- Fill remaining missing engineered features with forward fill, backward fill, median fallback
- Clip outliers with IQR-based clipping

### 3) Data normalization

Implemented in: preprocessing.py

Supported normalization modes:

- Min-Max scaling to [0, 1]
- Z-Score standardization

Min-Max formula:

X_scaled = (X - X_min) / (X_max - X_min)

### 4) Feature engineering

Implemented in: preprocessing.py

Features added:

- Returns
- Log Returns
- Moving Average (MA)
- Exponential Moving Average (EMA)
- RSI
- MACD + Signal line
- Bollinger Bands
- ATR
- Volatility
- Spread features

### 5) Sliding window generation

Implemented in: preprocessing.py

Transforms data into supervised samples:

- Input sequence length = lookback
- Label = future close at forecast horizon

Example:

[100, 101, 102, 103, 104] -> predict 105

### 6) Neural network architectures

Implemented in: models.py

Available models:

- Feedforward network
- RNN
- LSTM
- GRU
- 1D CNN
- Hybrid LSTM + Dense

Configurable activation (for side-by-side experiments):

- relu
- sigmoid
- tanh

### 7) Training

Implemented in: trainer.py

Training components:

- Forward pass
- Loss computation
- Backpropagation
- Optimizer update
- Learning-rate scheduler
- Early stopping

Optimizers supported:

- Adam
- SGD
- RMSProp
- AdaGrad

Loss functions supported:

- MSE (Mean Squared Error) — classical L²; minimizes squared deviations
- MAE (Mean Absolute Error) — classical L¹; minimizes absolute deviations
- Huber — robust to outliers; hybrid MSE/MAE behavior
- RMSE (Root Mean Squared Error) — MSE in price units for interpretability
- LogCosh — smooth approximation of MAE; reduces outlier impact
- **Quantile** — asymmetric; predicts confidence bounds (upper/lower percentiles)
- **Pinball** — directional asymmetric loss; penalizes miss-direction more
- **SMAPE** (Symmetric MAPE) — percentage-based; good for return prediction
- **DirectionWeighted** — composite loss; emphasizes buy/sell correctness over magnitude
- **HuberLogCombined** — combines Huber (robust) + LogCosh (smooth) for stable convergence
- **AdaptiveWeighted** — emphasizes harder-to-predict samples (weights by error magnitude)
- **ReturnVolatility** — adapts to market regime; tighter predictions in low-vol periods

### 8) Prediction

Implemented in: predict_visualize.py

Prediction flow:

- Build model
- Run inference on test windows
- Inverse-transform predictions back to price scale

Output example:

- Current price: 42000
- Predicted price: 42350

### 9) Trading signal generation

Implemented in: trading_strategy.py

Signal methods:

- Simple rule: BUY if predicted_price > current_price, else SELL
- Threshold rule: BUY if predicted_return > threshold, SELL if < -threshold, else HOLD

### 10) Risk management

Implemented in: trading_strategy.py

Methods included:

- Stop loss
- Take profit
- Position sizing by fixed risk per trade

Example logic:

- stop_loss = entry_price * (1 - stop_loss_pct)
- take_profit = entry_price * (1 + take_profit_pct)

### 11) Execution

Implemented in: trading_strategy.py and deploy_live.py

Execution modes:

- paper mode (simulated fills)
- live mode hook (exchange request structure in place)

Deployment loop performs:

- fetch latest data
- preprocess
- predict
- signal generation
- risk controls
- execution call

---

## Evaluation metrics

Implemented in: predict_visualize.py and trading_strategy.py

Prediction metrics:

- MAE
- RMSE
- MAPE
- R^2
- Direction Accuracy

Trading metrics:

- Sharpe Ratio
- Maximum Drawdown
- Profit Factor

---

## Files and roles

- main.py: general training and comparison entry point
- lstm_trading_pipeline.py: dedicated 11-step LSTM trading workflow
- deploy_live.py: iterative deployment loop for live-like operation
- data_fetcher.py: source adapters and market data cleaning
- preprocessing.py: feature engineering, scaling, windowing
- models.py: neural network architectures + activation selection
- trainer.py: optimization and training loop
- predict_visualize.py: inference, metrics, plotting
- trading_strategy.py: signal logic, risk management, execution

---

## How to run

### Quick test

python main.py --ticker BTC-USD --source yahoo --model lstm --activation relu --epochs 1

### Better training run

python main.py --ticker BTC-USD --source yahoo --model lstm --activation tanh --epochs 50

### Compare activations fairly

python main.py --ticker BTC-USD --source yahoo --model lstm --activation relu --epochs 50
python main.py --ticker BTC-USD --source yahoo --model lstm --activation sigmoid --epochs 50
python main.py --ticker BTC-USD --source yahoo --model lstm --activation tanh --epochs 50

### Full LSTM trading pipeline

python lstm_trading_pipeline.py --ticker BTC-USD --source yahoo --activation relu --execution-mode paper

---

## Important practical note

This project is a research and educational trading framework.

Real-world deployment should additionally include:

- transaction costs and slippage
- latency handling
- robust exchange authentication and retries
- strict portfolio-level risk limits
- walk-forward and out-of-sample validation
