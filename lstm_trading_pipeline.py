"""Complete LSTM trading pipeline implementing the 11 requested algorithm stages."""

import argparse
import torch

from data_fetcher import fetch_data
from preprocessing import prepare_dataset, inverse_transform_close
from models import build_model
from trainer import train_model
from predict_visualize import predict, compute_metrics
from trading_strategy import (
    threshold_trade_decision,
    risk_controls,
    position_size,
    execute_order,
)


def run_pipeline(
    ticker: str,
    source: str,
    lookback: int,
    epochs: int,
    batch_size: int,
    lr: float,
    threshold: float,
    account_balance: float,
    risk_per_trade: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    execution_mode: str,
    activation: str,
):
    print("\n1) Market Data Collection")
    df = fetch_data(ticker=ticker, source=source, period="5y", interval="1d")
    print(f"   Collected rows: {len(df)}")

    print("2) Data Cleaning")
    print("   Applied: remove missing, deduplicate, normalize timestamps, sort by timestamp")

    print("3) Data Normalization")
    print("4) Feature Engineering")
    print("5) Sliding Window Creation")
    dataset = prepare_dataset(df, lookback=lookback, normalization="minmax")
    print(f"   Windowed train/test: {len(dataset['X_train'])}/{len(dataset['X_test'])}")

    print("6) LSTM Model Architecture")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_model(
        model_type="lstm",
        lookback=lookback,
        n_features=dataset["X_train"].shape[2],
        device=device,
        activation=activation,
    )

    print("7) Training")
    train_model(
        model=model,
        X_train=dataset["X_train"],
        y_train=dataset["y_train"],
        X_test=dataset["X_test"],
        y_test=dataset["y_test"],
        device=device,
        epochs=epochs,
        batch_size=batch_size,
        learning_rate=lr,
        optimizer_name="adam",
        loss_name="mse",
    )

    print("8) Prediction")
    preds_scaled = predict(model, dataset["X_test"], device)
    preds = inverse_transform_close(preds_scaled, dataset["close_scaler"])
    actuals = inverse_transform_close(dataset["y_test"], dataset["close_scaler"])
    metrics = compute_metrics(actuals, preds)
    print(f"   Current price:   {actuals[-1]:.4f}")
    print(f"   Predicted price: {preds[-1]:.4f}")

    print("9) Trading Signal")
    signal = threshold_trade_decision(actuals[-1], preds[-1], threshold=threshold)
    print(f"   Signal: {signal}")

    print("10) Risk Management")
    risk = risk_controls(
        entry_price=actuals[-1],
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
    )
    qty = position_size(
        account_balance=account_balance,
        risk_per_trade=risk_per_trade,
        entry_price=actuals[-1],
        stop_loss_price=risk["stop_loss"],
    )
    print(f"   Stop loss:   {risk['stop_loss']:.4f}")
    print(f"   Take profit: {risk['take_profit']:.4f}")
    print(f"   Position qty:{qty:.6f}")

    print("11) Automated Trading Execution")
    if signal in {"BUY", "SELL"} and qty > 0:
        order = execute_order(
            symbol=ticker.replace("-", "") if source == "binance" else ticker,
            side=signal,
            quantity=qty,
            mode=execution_mode,
        )
        print(f"   Order status: {order['status']} ({order['mode']})")
    else:
        print("   No order sent (HOLD signal or zero quantity)")

    print("\nEvaluation:")
    for k, v in metrics.items():
        print(f"   {k}: {v:.4f}")


def main():
    parser = argparse.ArgumentParser(description="LSTM Trading Model Pipeline")
    parser.add_argument("--ticker", type=str, default="BTC-USD")
    parser.add_argument("--source", type=str, default="yahoo", choices=["yahoo", "binance", "alphavantage"])
    parser.add_argument("--lookback", type=int, default=60)
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--threshold", type=float, default=0.002)
    parser.add_argument("--account-balance", type=float, default=10000.0)
    parser.add_argument("--risk-per-trade", type=float, default=0.01)
    parser.add_argument("--stop-loss-pct", type=float, default=0.02)
    parser.add_argument("--take-profit-pct", type=float, default=0.05)
    parser.add_argument("--execution-mode", type=str, default="paper", choices=["paper", "live"])
    parser.add_argument("--activation", type=str, default="relu", choices=["relu", "sigmoid", "tanh"])
    args = parser.parse_args()

    run_pipeline(
        ticker=args.ticker,
        source=args.source,
        lookback=args.lookback,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        threshold=args.threshold,
        account_balance=args.account_balance,
        risk_per_trade=args.risk_per_trade,
        stop_loss_pct=args.stop_loss_pct,
        take_profit_pct=args.take_profit_pct,
        execution_mode=args.execution_mode,
        activation=args.activation,
    )


if __name__ == "__main__":
    main()
