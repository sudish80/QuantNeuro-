"""Trading strategy algorithms and trading-specific evaluation metrics."""

import hashlib
import hmac
import os
import time
from urllib.parse import urlencode

import numpy as np
import requests


def generate_signals(actuals: np.ndarray, predictions: np.ndarray, threshold: float = 0.0) -> np.ndarray:
    """
    FIX #3: Generate signals based on RETURNS, not prices.
    
    CORRECTED approach: Compare predicted returns vs actual returns
    to generate trading signals.
    
    Args:
        actuals: Actual prices (or returns)
        predictions: Predicted prices (or returns)
        threshold: Signal threshold
    
    Returns:
        signals: 1 (buy), -1 (sell), 0 (hold)
    
    NOTE: If input is prices, convert to returns first.
    This assumes prices are roughly log-normal (0-$1000 range).
    """
    if len(actuals) != len(predictions):
        raise ValueError("actuals and predictions must have the same length")
    
    # Check if inputs are prices or returns
    # Heuristic: if values > 1 and differences are small, likely prices
    actual_mean = np.mean(np.abs(actuals))
    actual_max_diff = np.max(np.diff(actuals))
    
    is_price = actual_mean > 1.0 and actual_max_diff < actual_mean * 0.1
    
    if is_price:
        # Convert prices to returns
        actual_returns = np.diff(actuals) / (actuals[:-1] + 1e-12)
        predicted_returns = np.diff(predictions) / (predictions[:-1] + 1e-12)
        
        # Signals based on return comparison
        signals = np.zeros(len(actuals) - 1, dtype=np.int8)  # One fewer sample
        return_delta = predicted_returns - actual_returns
    else:
        # Already returns
        signals = np.zeros(len(actuals), dtype=np.int8)
        return_delta = predictions - actuals
    
    # Generate signals based on return advantage
    signals[return_delta > threshold] = 1   # Buy if predicted return > actual
    signals[return_delta < -threshold] = -1  # Sell if predicted return < actual
    
    return signals


def generate_signals_return_based(prices: np.ndarray, predicted_returns: np.ndarray,
                                 actual_returns: np.ndarray, threshold: float = 0.0) -> np.ndarray:
    """
    PREFERRED METHOD: Generate signals when model predicts RETURNS directly.
    
    This is semantically correct: model predicts future returns, we trade on that.
    
    Args:
        prices: Historical prices (for reference)
        predicted_returns: Predicted returns from model
        actual_returns: Realized returns
        threshold: Signal threshold for return advantage
    
    Returns:
        signals: 1 (buy if pred_return > threshold), -1 (sell if pred_return < -threshold), 0 (hold)
    """
    if len(predicted_returns) != len(actual_returns):
        raise ValueError("predicted_returns and actual_returns must have the same length")
    
    signals = np.zeros(len(predicted_returns), dtype=np.int8)
    
    # Signal based on predicted return magnitude
    # BUY: predicted return > threshold (e.g., > 0.5% expected gain)
    # SELL: predicted return < -threshold (e.g., < -0.5% expected loss)
    signals[predicted_returns > threshold] = 1
    signals[predicted_returns < -threshold] = -1
    
    return signals


def compute_trading_metrics(actuals: np.ndarray, signals: np.ndarray) -> dict:
    """Compute Sharpe ratio, max drawdown, and profit factor using simple daily returns."""
    if len(actuals) < 2:
        return {"Sharpe Ratio": 0.0, "Max Drawdown (%)": 0.0, "Profit Factor": 0.0}

    returns = np.diff(actuals) / (actuals[:-1] + 1e-12)
    pos = signals[:-1]
    strategy_returns = returns * pos

    mean_ret = np.mean(strategy_returns)
    std_ret = np.std(strategy_returns)
    sharpe = float((mean_ret / (std_ret + 1e-12)) * np.sqrt(252))

    equity_curve = np.cumprod(1 + strategy_returns)
    running_max = np.maximum.accumulate(equity_curve)
    drawdown = (equity_curve - running_max) / (running_max + 1e-12)
    max_drawdown = float(np.min(drawdown) * 100.0)

    gross_profit = np.sum(strategy_returns[strategy_returns > 0])
    gross_loss = np.abs(np.sum(strategy_returns[strategy_returns < 0]))
    profit_factor = float(gross_profit / (gross_loss + 1e-12))

    return {
        "Sharpe Ratio": sharpe,
        "Max Drawdown (%)": max_drawdown,
        "Profit Factor": profit_factor,
    }


def simple_trade_decision(current_price: float, predicted_price: float) -> str:
    """Basic rule-based signal as requested: BUY if predicted > current, else SELL."""
    return "BUY" if predicted_price > current_price else "SELL"


def threshold_trade_decision(current_price: float, predicted_price: float, threshold: float = 0.002) -> str:
    """Threshold-based trading signal using predicted return."""
    predicted_return = (predicted_price - current_price) / (current_price + 1e-12)
    if predicted_return > threshold:
        return "BUY"
    if predicted_return < -threshold:
        return "SELL"
    return "HOLD"


def risk_controls(
    entry_price: float,
    stop_loss_pct: float = 0.02,
    take_profit_pct: float = 0.05,
) -> dict:
    """Compute stop-loss and take-profit levels."""
    return {
        "stop_loss": entry_price * (1.0 - stop_loss_pct),
        "take_profit": entry_price * (1.0 + take_profit_pct),
    }


def position_size(
    account_balance: float,
    risk_per_trade: float,
    entry_price: float,
    stop_loss_price: float,
) -> float:
    """Position sizing via fixed fractional risk model."""
    risk_amount = account_balance * risk_per_trade
    unit_risk = abs(entry_price - stop_loss_price)
    if unit_risk <= 0:
        return 0.0
    return risk_amount / unit_risk


def execute_order(
    symbol: str,
    side: str,
    quantity: float,
    mode: str = "paper",
    base_url: str = "https://api.binance.com",
    timeout: int = 20,
) -> dict:
    """
    Execute order in paper mode or call exchange API endpoint in live mode.

    Notes:
    - Paper mode logs simulated execution only.
    - Live mode uses Binance test order endpoint shape and requires external auth wiring.
    """
    if mode == "paper":
        return {
            "status": "FILLED",
            "mode": "paper",
            "symbol": symbol,
            "side": side,
            "executedQty": quantity,
        }

    # Live mode requires API key header plus signed payload.
    endpoint = f"{base_url}/api/v3/order/test"
    api_key = os.getenv("BINANCE_API_KEY", "")
    api_secret = os.getenv("BINANCE_API_SECRET", "")
    if not api_key or not api_secret:
        raise ValueError("BINANCE_API_KEY and BINANCE_API_SECRET are required for live mode")

    payload = {
        "symbol": symbol,
        "side": side,
        "type": "MARKET",
        "quantity": quantity,
        "timestamp": int(time.time() * 1000),
        "recvWindow": 5000,
    }
    query = urlencode(payload)
    signature = hmac.new(api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
    payload["signature"] = signature
    headers = {
        "X-MBX-APIKEY": api_key,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    response = requests.post(endpoint, data=payload, headers=headers, timeout=timeout)
    response.raise_for_status()
    return {
        "status": "ACCEPTED",
        "mode": "live",
        "symbol": symbol,
        "side": side,
        "executedQty": quantity,
        "response": response.json() if response.text else {},
    }
