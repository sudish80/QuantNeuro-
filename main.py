"""
Stock & Crypto Price Prediction using Deep Neural Networks
==========================================================

Based on the mathematical framework from:
  "Mathematical Introduction to Deep Learning: Methods, Implementations,
   and Theory" — Jentzen, Kuckuck, von Wurstemberger (2023)
  arXiv: 2310.20360v3

Core concepts applied from the PDF:
  - Deep feedforward networks as function approximators (Ch. 2, Def 2.1.1–2.1.3)
  - ReLU activation and universal approximation (Ch. 4, Theorem 4.2.1)
  - Empirical risk minimization with MSE loss (Ch. 3)
  - SGD-based optimization with Adam (Ch. 5, Sections 5.1–5.7)
  - Backpropagation for gradient computation (Section 5.6)

Usage:
    python main.py                          # Run with defaults (BTC-USD, LSTM)
    python main.py --ticker AAPL            # Predict Apple stock
    python main.py --ticker ETH-USD --model hybrid --epochs 150
    python main.py --compare                # Compare all 3 models on one ticker

Author: Generated using concepts from Jentzen et al. (2023)
"""

import argparse
import os
import torch

from data_fetcher import fetch_data
from preprocessing import prepare_dataset, inverse_transform_close
from models import build_model
from trainer import train_model
from predict_visualize import (
    predict,
    inverse_transform_predictions,
    compute_metrics,
    print_metrics,
    plot_training_history,
    plot_predictions,
    plot_model_comparison,
)
from trading_strategy import generate_signals, compute_trading_metrics


def run_single_model(
    ticker: str,
    model_type: str,
    lookback: int,
    epochs: int,
    batch_size: int,
    learning_rate: float,
    device: torch.device,
    source: str,
    normalization: str,
    optimizer_name: str,
    loss_name: str,
    activation: str,
    alpha_vantage_key: str | None,
    save_plots: bool = False,
) -> dict:
    """Train and evaluate a single model on the given ticker."""
    print(f"\n{'='*60}")
    print(f"  Ticker: {ticker} | Model: {model_type.upper()}")
    print(f"{'='*60}")

    # 1. Fetch data
    print("\n[1/4] Fetching data...")
    df = fetch_data(
        ticker=ticker,
        period="5y",
        source=source,
        alpha_vantage_key=alpha_vantage_key,
    )
    print(f"  Downloaded {len(df)} rows ({df.index[0].date()} to {df.index[-1].date()})")

    # 2. Preprocess
    print("\n[2/4] Preprocessing...")
    dataset = prepare_dataset(df, lookback=lookback, normalization=normalization)
    n_features = dataset["X_train"].shape[2]
    print(f"  Features: {n_features} | Lookback: {lookback}")
    print(f"  Train samples: {len(dataset['X_train'])} | Test samples: {len(dataset['X_test'])}")

    # 3. Build and train model
    print(f"\n[3/4] Training {model_type.upper()} model...")
    model = build_model(model_type, lookback, n_features, device, activation=activation)
    history = train_model(
        model=model,
        X_train=dataset["X_train"],
        y_train=dataset["y_train"],
        X_test=dataset["X_test"],
        y_test=dataset["y_test"],
        device=device,
        epochs=epochs,
        batch_size=batch_size,
        learning_rate=learning_rate,
        optimizer_name=optimizer_name,
        loss_name=loss_name,
    )

    # 4. Evaluate
    print(f"\n[4/4] Evaluating...")
    test_preds = predict(model, dataset["X_test"], device)
    preds_price = inverse_transform_close(test_preds, dataset["close_scaler"])
    actuals_price = inverse_transform_close(dataset["y_test"], dataset["close_scaler"])
    metrics = compute_metrics(actuals_price, preds_price)
    signals = generate_signals(actuals_price, preds_price)
    metrics.update(compute_trading_metrics(actuals_price, signals))
    print_metrics(metrics, ticker, model_type.upper())

    # Plots
    out_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(out_dir, exist_ok=True)

    prefix = f"{out_dir}/{ticker.replace('-', '_')}_{model_type}"

    plot_training_history(
        history, ticker, model_type.upper(),
        save_path=f"{prefix}_training.png",
    )

    # Get dates for test set
    test_start = lookback + len(dataset["X_train"])
    test_dates = df.index[test_start : test_start + len(actuals_price)]
    if len(test_dates) != len(actuals_price):
        test_dates = None

    plot_predictions(
        actuals_price, preds_price, ticker, model_type.upper(),
        dates=test_dates,
        save_path=f"{prefix}_predictions.png",
    )

    return metrics


def run_comparison(
    ticker: str,
    lookback: int,
    epochs: int,
    batch_size: int,
    learning_rate: float,
    device: torch.device,
    source: str,
    normalization: str,
    optimizer_name: str,
    loss_name: str,
    activation: str,
    alpha_vantage_key: str | None,
):
    """Compare all three model architectures on the same data."""
    print(f"\n{'#'*60}")
    print(f"  MODEL COMPARISON — {ticker}")
    print(f"{'#'*60}")

    all_results = {}
    for model_type in ["feedforward", "rnn", "lstm", "gru", "cnn", "hybrid"]:
        metrics = run_single_model(
            ticker=ticker,
            model_type=model_type,
            lookback=lookback,
            epochs=epochs,
            batch_size=batch_size,
            learning_rate=learning_rate,
            device=device,
            source=source,
            normalization=normalization,
            optimizer_name=optimizer_name,
            loss_name=loss_name,
            activation=activation,
            alpha_vantage_key=alpha_vantage_key,
            save_plots=True,
        )
        all_results[model_type.upper()] = metrics

    print(f"\n{'='*60}")
    print("  COMPARISON SUMMARY")
    print(f"{'='*60}")
    for name, m in all_results.items():
        print(f"  {name:<14} MAE: {m['MAE']:>10.2f}  RMSE: {m['RMSE']:>10.2f}  "
              f"R²: {m['R²']:>6.4f}  MAPE: {m['MAPE (%)']:>6.2f}%")

    out_dir = os.path.join(os.path.dirname(__file__), "output")
    plot_model_comparison(
        all_results,
        save_path=os.path.join(out_dir, f"{ticker.replace('-', '_')}_comparison.png"),
    )
    return all_results


def main():
    parser = argparse.ArgumentParser(
        description="Stock & Crypto Price Prediction with Deep Neural Networks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python main.py --ticker BTC-USD --source yahoo --model lstm
  python main.py --ticker AAPL --model hybrid --epochs 200
  python main.py --ticker ETH-USD --compare
    python main.py --ticker BTCUSDT --source binance --model gru
    python main.py --ticker BTC-USD --model lstm --activation sigmoid
    python main.py --ticker MSFT --source alphavantage --alpha-vantage-key YOUR_KEY
        """,
    )
    parser.add_argument("--ticker", type=str, default="BTC-USD",
                        help="Ticker symbol (e.g., AAPL, BTC-USD, ETH-USD)")
    parser.add_argument("--source", type=str, default="yahoo",
                        choices=["yahoo", "binance", "alphavantage"],
                        help="Data source")
    parser.add_argument("--model", type=str, default="lstm",
                        choices=["feedforward", "rnn", "lstm", "gru", "cnn", "hybrid"],
                        help="Model architecture")
    parser.add_argument("--lookback", type=int, default=60,
                        help="Lookback window (number of past days)")
    parser.add_argument("--epochs", type=int, default=100,
                        help="Maximum training epochs")
    parser.add_argument("--allow-short-training", action="store_true",
                        help="Allow fewer than 20 epochs (intended for quick smoke tests)")
    parser.add_argument("--batch-size", type=int, default=64,
                        help="Mini-batch size for SGD")
    parser.add_argument("--lr", type=float, default=1e-3,
                        help="Initial learning rate")
    parser.add_argument("--normalization", type=str, default="minmax",
                        choices=["minmax", "zscore"],
                        help="Feature normalization algorithm")
    parser.add_argument("--optimizer", type=str, default="adam",
                        choices=["adam", "sgd", "rmsprop", "adagrad"],
                        help="Training optimizer")
    parser.add_argument("--loss", type=str, default="mse",
                        choices=["mse", "mae", "huber"],
                        help="Regression loss function")
    parser.add_argument("--activation", type=str, default="relu",
                        choices=["relu", "sigmoid", "tanh"],
                        help="Hidden activation function for model heads")
    parser.add_argument("--alpha-vantage-key", type=str, default=None,
                        help="Alpha Vantage API key (required when --source alphavantage)")
    parser.add_argument("--compare", action="store_true",
                        help="Compare all three model types")
    parser.add_argument("--save-plots", action="store_true",
                        help="Save plots to output/ directory")

    args = parser.parse_args()

    if args.epochs < 20 and not args.allow_short_training:
        print("\n  Epochs too low for stable training; upgrading to 20.")
        print("  Use --allow-short-training if you intentionally want a smoke test.")
        args.epochs = 20

    # Device selection
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"\n  Device: {device}")
    if device.type == "cuda":
        print(f"  GPU: {torch.cuda.get_device_name(0)}")

    if args.compare:
        run_comparison(
            ticker=args.ticker,
            lookback=args.lookback,
            epochs=args.epochs,
            batch_size=args.batch_size,
            learning_rate=args.lr,
            device=device,
            source=args.source,
            normalization=args.normalization,
            optimizer_name=args.optimizer,
            loss_name=args.loss,
            activation=args.activation,
            alpha_vantage_key=args.alpha_vantage_key,
        )
    else:
        run_single_model(
            ticker=args.ticker,
            model_type=args.model,
            lookback=args.lookback,
            epochs=args.epochs,
            batch_size=args.batch_size,
            learning_rate=args.lr,
            device=device,
            source=args.source,
            normalization=args.normalization,
            optimizer_name=args.optimizer,
            loss_name=args.loss,
            activation=args.activation,
            alpha_vantage_key=args.alpha_vantage_key,
            save_plots=args.save_plots,
        )


if __name__ == "__main__":
    main()
