"""Simple deployment loop for real-time prediction and signal generation."""

import argparse
import time
import torch
import numpy as np

from data_fetcher import fetch_data
from preprocessing import prepare_dataset, inverse_transform_close
from models import build_model
from trainer import train_model
from trading_strategy import simple_trade_decision


def run_live_loop(
    ticker: str,
    source: str,
    model_type: str,
    lookback: int,
    interval_seconds: int,
    iterations: int,
    optimizer: str,
    loss: str,
    activation: str,
):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = None

    for step in range(iterations):
        print(f"\n[Live Iteration {step + 1}/{iterations}] Fetching latest data...")
        df = fetch_data(ticker=ticker, source=source, period="2y", interval="1d")
        dataset = prepare_dataset(df, lookback=lookback)

        if model is None:
            model = build_model(
                model_type,
                lookback,
                dataset["X_train"].shape[2],
                device,
                activation=activation,
            )
            train_model(
                model=model,
                X_train=dataset["X_train"],
                y_train=dataset["y_train"],
                X_test=dataset["X_test"],
                y_test=dataset["y_test"],
                device=device,
                epochs=8,
                batch_size=64,
                learning_rate=1e-3,
                optimizer_name=optimizer,
                loss_name=loss,
            )

        latest_window = dataset["X_test"][-1:]
        with torch.no_grad():
            pred_scaled = model(torch.tensor(latest_window, dtype=torch.float32).to(device)).cpu().numpy()

        predicted_price = float(inverse_transform_close(pred_scaled, dataset["close_scaler"])[0])
        current_price = float(df["Close"].iloc[-1])
        signal = simple_trade_decision(current_price=current_price, predicted_price=predicted_price)

        print(f"Current Price:   {current_price:.4f}")
        print(f"Predicted Price: {predicted_price:.4f}")
        print(f"Signal:          {signal}")
        print("Execution:       Paper-trade placeholder (hook exchange API here)")

        if step < iterations - 1:
            time.sleep(interval_seconds)


def main():
    parser = argparse.ArgumentParser(description="Live deployment loop for stock/crypto predictor")
    parser.add_argument("--ticker", type=str, default="BTC-USD")
    parser.add_argument("--source", type=str, default="yahoo", choices=["yahoo", "binance", "alphavantage"])
    parser.add_argument("--model", type=str, default="gru", choices=["feedforward", "rnn", "lstm", "gru", "cnn", "hybrid"])
    parser.add_argument("--lookback", type=int, default=60)
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--optimizer", type=str, default="adam", choices=["adam", "sgd", "rmsprop", "adagrad"])
    parser.add_argument("--loss", type=str, default="mse", choices=["mse", "mae", "huber"])
    parser.add_argument("--activation", type=str, default="relu", choices=["relu", "sigmoid", "tanh"])
    args = parser.parse_args()

    run_live_loop(
        ticker=args.ticker,
        source=args.source,
        model_type=args.model,
        lookback=args.lookback,
        interval_seconds=args.interval_seconds,
        iterations=args.iterations,
        optimizer=args.optimizer,
        loss=args.loss,
        activation=args.activation,
    )


if __name__ == "__main__":
    main()
