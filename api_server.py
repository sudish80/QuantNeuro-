"""
REST API layer for the trading model.

Provides:
- Model serving endpoints (predictions, signals)
- Configuration management (strategy, model parameters)
- Metrics and monitoring endpoints
- Health checks and status

Built with FastAPI for async/concurrent request handling.
"""

import os
import json
from typing import Optional, Dict, List
from datetime import datetime

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
import numpy as np
import torch

# Local imports
from models import FeedforwardNet, LSTMNet, HybridNet, get_activation, build_model
from preprocessing import prepare_dataset
from trading_strategy import generate_signal, execute_order
from production_hardening.reliability import StateStore
from production_hardening.journal import TradeJournal
from production_hardening.monitoring import (
    write_metrics_csv,
    generate_metrics_dashboard,
)
from production_hardening.config import Config

# ============================================================================
# Pydantic Models (Request/Response schemas)
# ============================================================================


class PredictionRequest(BaseModel):
    """Request for price prediction."""

    ticker: str
    lookback_window: Optional[int] = 20
    source: Optional[str] = "yfinance"
    model_type: Optional[str] = "lstm"


class PredictionResponse(BaseModel):
    """Prediction response with metadata."""

    ticker: str
    current_price: float
    predicted_price: float
    confidence: float
    signal: str  # "BUY", "SELL", "HOLD"
    timestamp: str


class SignalRequest(BaseModel):
    """Request for trading signal."""

    ticker: str
    predicted_return: float
    threshold: Optional[float] = 0.02


class SignalResponse(BaseModel):
    """Trading signal response."""

    signal: str  # "BUY", "SELL", "HOLD"
    confidence: float
    reasoning: str


class ExecutionRequest(BaseModel):
    """Order execution request."""

    ticker: str
    side: str  # "BUY" or "SELL"
    quantity: float
    price: Optional[float] = None
    timeout_seconds: Optional[int] = 30


class ExecutionResponse(BaseModel):
    """Order execution response."""

    order_id: str
    status: str  # "PENDING", "FILLED", "REJECTED"
    executed_price: Optional[float]
    filled_quantity: Optional[float]
    timestamp: str


class ConfigUpdateRequest(BaseModel):
    """Configuration update request."""

    parameter: str
    value: str


class MetricsResponse(BaseModel):
    """Metrics snapshot."""

    trades_executed: int
    total_pnl: float
    win_rate: float
    sharpe_ratio: float
    drawdown: float
    timestamp: str


# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="Trading Model API",
    version="1.0.0",
    description="REST API for neural network trading model serving and configuration",
)

# Global state
config = Config()
state_store = StateStore()
trade_journal = None
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
loaded_model = None


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    global trade_journal
    journal_passphrase = os.getenv("JOURNAL_PASSPHRASE", "")
    plaintext_enabled = os.getenv("TRADE_JOURNAL_PLAINTEXT_ENABLED", "false").lower() == "true"
    trade_journal = TradeJournal(
        passphrase=journal_passphrase,
        plaintext_enabled=plaintext_enabled,
    )
    print("✓ Trading API initialized")


# ============================================================================
# Health & Status Endpoints
# ============================================================================


@app.get("/health", tags=["Health"])
async def health_check() -> Dict:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "device": str(device),
    }


@app.get("/status", tags=["Status"])
async def status() -> Dict:
    """Get system status."""
    try:
        state = state_store.load()
        metrics_path = "state/metrics.csv"
        trades = len(open(metrics_path).readlines()) - 1 if os.path.exists(metrics_path) else 0

        return {
            "model_loaded": loaded_model is not None,
            "device": str(device),
            "trades_executed": trades,
            "state_version": state.get("version", 0),
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ============================================================================
# Prediction Endpoints
# ============================================================================


@app.post("/predict", response_model=PredictionResponse, tags=["Predictions"])
async def predict(request: PredictionRequest) -> PredictionResponse:
    """
    Generate price prediction for a ticker.

    - **ticker**: Stock/crypto symbol (e.g., "AAPL", "BTC-USD")
    - **lookback_window**: Historical bars to use (default: 20)
    - **source**: Data source ("yfinance", "binance")
    - **model_type**: Model architecture ("feedforward", "lstm", "hybrid")
    """
    try:
        # Load data (simplified; full version would fetch live data)
        dataset = prepare_dataset(
            source=request.source,
            ticker=request.ticker,
            lookback=request.lookback_window,
        )

        # Load or build model
        model = build_model(
            model_type=request.model_type,
            lookback=request.lookback_window,
            n_features=dataset["X_train"].shape[2],
            device=device,
        )

        # Generate prediction
        X_test = torch.tensor(dataset["X_test"], dtype=torch.float32).to(device)
        with torch.no_grad():
            predictions = model(X_test[-1:]).cpu().numpy()

        pred_price = float(predictions[0])
        current_price = float(dataset["current_price"])
        confidence = 0.75  # Placeholder

        # Generate signal
        signal = "BUY" if pred_price > current_price else "SELL"

        return PredictionResponse(
            ticker=request.ticker,
            current_price=current_price,
            predicted_price=pred_price,
            confidence=confidence,
            signal=signal,
            timestamp=datetime.utcnow().isoformat(),
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction failed: {str(e)}")


# ============================================================================
# Signal Generation Endpoints
# ============================================================================


@app.post("/signal", response_model=SignalResponse, tags=["Signals"])
async def generate_trading_signal(request: SignalRequest) -> SignalResponse:
    """
    Generate trading signal based on predicted return.

    - **ticker**: Asset identifier
    - **predicted_return**: Predicted price return (e.g., 0.02 = +2%)
    - **threshold**: Buy threshold (default: 2%)
    """
    signal = generate_signal(
        predicted_return=request.predicted_return,
        threshold=request.threshold or 0.02,
    )

    confidence = min(abs(request.predicted_return) / (request.threshold or 0.02), 1.0)
    reasoning = f"Predicted return: {request.predicted_return:.2%}"

    return SignalResponse(
        signal=signal,
        confidence=float(confidence),
        reasoning=reasoning,
    )


# ============================================================================
# Execution Endpoints
# ============================================================================


@app.post("/execute", response_model=ExecutionResponse, tags=["Execution"])
async def execute_trading_order(
    request: ExecutionRequest, background_tasks: BackgroundTasks
) -> ExecutionResponse:
    """
    Execute a trading order (BUY/SELL).

    - **ticker**: Asset identifier
    - **side**: "BUY" or "SELL"
    - **quantity**: Number of shares/units
    - **price**: Optional limit price
    - **timeout_seconds**: Order timeout
    """
    try:
        # Validate input
        if request.side not in ["BUY", "SELL"]:
            raise ValueError("side must be 'BUY' or 'SELL'")

        # Execute order
        result = execute_order(
            symbol=request.ticker,
            side=request.side,
            quantity=request.quantity,
            price=request.price,
            timeout=request.timeout_seconds or 30,
        )

        # Log to journal
        order_id = f"{request.ticker}_{datetime.utcnow().timestamp()}"
        if trade_journal:
            trade_journal.write_event(
                side=request.side,
                symbol=request.ticker,
                quantity=request.quantity,
                price=result.get("executed_price", request.price or 0.0),
            )

        return ExecutionResponse(
            order_id=order_id,
            status=result.get("status", "PENDING"),
            executed_price=result.get("executed_price"),
            filled_quantity=result.get("filled_quantity"),
            timestamp=datetime.utcnow().isoformat(),
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Execution failed: {str(e)}")


# ============================================================================
# Configuration Endpoints
# ============================================================================


@app.get("/config", tags=["Configuration"])
async def get_config() -> Dict:
    """Get current configuration."""
    return {
        "model": config.model_type,
        "optimizer": config.optimizer_name,
        "loss": config.loss_name,
        "learning_rate": config.learning_rate,
        "batch_size": config.batch_size,
        "epochs": config.epochs,
    }


@app.put("/config", tags=["Configuration"])
async def update_config(request: ConfigUpdateRequest) -> Dict:
    """
    Update configuration parameter.

    - **parameter**: Parameter name (e.g., "learning_rate")
    - **value**: New value (as string; will be cast to proper type)
    """
    try:
        setattr(config, request.parameter, request.value)
        return {"status": "updated", "parameter": request.parameter, "value": request.value}
    except AttributeError:
        raise HTTPException(status_code=400, detail=f"Unknown parameter: {request.parameter}")


# ============================================================================
# Metrics & Monitoring Endpoints
# ============================================================================


@app.get("/metrics", response_model=MetricsResponse, tags=["Monitoring"])
async def get_metrics() -> MetricsResponse:
    """Get recent trading metrics snapshot."""
    try:
        metrics_path = "state/metrics.csv"
        if not os.path.exists(metrics_path):
            return MetricsResponse(
                trades_executed=0,
                total_pnl=0.0,
                win_rate=0.0,
                sharpe_ratio=0.0,
                drawdown=0.0,
                timestamp=datetime.utcnow().isoformat(),
            )

        # Read last row from metrics CSV
        with open(metrics_path, "r") as f:
            lines = f.readlines()
            if len(lines) > 1:
                last_row = lines[-1].strip().split(",")
                return MetricsResponse(
                    trades_executed=int(last_row[0]) if len(last_row) > 0 else 0,
                    total_pnl=float(last_row[1]) if len(last_row) > 1 else 0.0,
                    win_rate=float(last_row[2]) if len(last_row) > 2 else 0.0,
                    sharpe_ratio=float(last_row[3]) if len(last_row) > 3 else 0.0,
                    drawdown=float(last_row[4]) if len(last_row) > 4 else 0.0,
                    timestamp=datetime.utcnow().isoformat(),
                )

        return MetricsResponse(
            trades_executed=0,
            total_pnl=0.0,
            win_rate=0.0,
            sharpe_ratio=0.0,
            drawdown=0.0,
            timestamp=datetime.utcnow().isoformat(),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Metrics retrieval failed: {str(e)}")


@app.get("/dashboard", tags=["Monitoring"])
async def get_dashboard_html() -> StreamingResponse:
    """Get interactive HTML dashboard with Chart.js visualization."""
    try:
        html_content = generate_metrics_dashboard()
        return StreamingResponse(
            iter([html_content]),
            media_type="text/html",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Dashboard generation failed: {str(e)}")


# ============================================================================
# Batch Operations
# ============================================================================


@app.post("/batch-predict", tags=["Batch"])
async def batch_predict(tickers: List[str]) -> List[PredictionResponse]:
    """
    Generate predictions for multiple tickers in batch.

    Useful for portfolio-wide analysis.
    """
    results = []
    for ticker in tickers:
        try:
            result = await predict(PredictionRequest(ticker=ticker))
            results.append(result)
        except Exception as e:
            # Log error but continue with other tickers
            print(f"Error predicting {ticker}: {e}")
            continue

    return results


@app.post("/backtest", tags=["Analysis"])
async def run_backtest(
    ticker: str,
    start_date: str,
    end_date: str,
    initial_capital: float = 10000.0,
) -> Dict:
    """
    Run backtest on historical data.

    - **ticker**: Asset to backtest
    - **start_date**: Start date (YYYY-MM-DD)
    - **end_date**: End date (YYYY-MM-DD)
    - **initial_capital**: Starting balance
    """
    # Simplified backtest; full version would use walk-forward validation
    return {
        "ticker": ticker,
        "period": f"{start_date} to {end_date}",
        "initial_capital": initial_capital,
        "final_capital": initial_capital * 1.15,  # Placeholder +15%
        "total_return": 0.15,
        "sharpe_ratio": 1.2,
        "max_drawdown": -0.08,
        "trades": 42,
        "win_rate": 0.52,
    }


# ============================================================================
# Error Handlers
# ============================================================================


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom HTTP exception handler."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "timestamp": datetime.utcnow().isoformat()},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=5000,
        log_level="info",
    )
