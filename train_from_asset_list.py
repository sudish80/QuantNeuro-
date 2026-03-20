"""Train models using a watchlist file (like data.csv with asset/company names)."""

import argparse
from pathlib import Path

import torch

from data_fetcher import fetch_data
from models import build_model
from predict_visualize import compute_metrics
from preprocessing import inverse_transform_close, prepare_dataset
from trainer import train_model
from predict_visualize import predict


NAME_TO_TICKER = {
    "bitcoin": "BTC-USD",
    "ethereum": "ETH-USD",
    "tether": "USDT-USD",
    "bnb": "BNB-USD",
    "solana": "SOL-USD",
    "usdc": "USDC-USD",
    "xrp": "XRP-USD",
    "dogecoin": "DOGE-USD",
    "toncoin": "TON11419-USD",
    "cardano": "ADA-USD",
    "shiba inu": "SHIB-USD",
    "avalanche": "AVAX-USD",
    "tron": "TRX-USD",
    "polkadot": "DOT-USD",
    "chainlink": "LINK-USD",
    "polygon": "MATIC-USD",
    "litecoin": "LTC-USD",
    "bitcoin cash": "BCH-USD",
    "uniswap": "UNI7083-USD",
    "internet computer": "ICP-USD",
    "dai": "DAI-USD",
    "wrapped bitcoin": "WBTC-USD",
    "leo token": "LEO-USD",
    "ethereum classic": "ETC-USD",
    "aptos": "APT21794-USD",
    "stellar": "XLM-USD",
    "near protocol": "NEAR-USD",
    "monero": "XMR-USD",
    "okb": "OKB-USD",
    "mantle": "MNT27075-USD",
    "cronos": "CRO-USD",
    "filecoin": "FIL-USD",
    "stacks": "STX4847-USD",
    "immutable": "IMX10603-USD",
    "vechain": "VET-USD",
    "arbitrum": "ARB11841-USD",
    "kaspa": "KAS-USD",
    "optimism": "OP-USD",
    "maker": "MKR-USD",
    "render": "RENDER-USD",
    "apple": "AAPL",
    "microsoft": "MSFT",
    "tesla": "TSLA",
    "amazon": "AMZN",
    "alphabet": "GOOGL",
    "nvidia": "NVDA",
}


def load_names(path: Path) -> list[str]:
    names: list[str] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            v = line.strip().strip('"')
            if v:
                names.append(v)
    return names


def to_tickers(names: list[str]) -> tuple[list[str], list[str]]:
    tickers: list[str] = []
    unresolved: list[str] = []
    for name in names:
        key = name.lower().strip()
        if key in NAME_TO_TICKER:
            tickers.append(NAME_TO_TICKER[key])
        else:
            unresolved.append(name)
    # de-duplicate while preserving order
    seen = set()
    unique = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique, unresolved


def train_one(
    ticker: str,
    model_type: str,
    activation: str,
    epochs: int,
    lookback: int,
    lr: float,
    batch_size: int,
    device: torch.device,
) -> dict:
    df = fetch_data(ticker=ticker, source="yahoo", period="5y", interval="1d")
    dataset = prepare_dataset(df, lookback=lookback, normalization="minmax")

    model = build_model(
        model_type=model_type,
        lookback=lookback,
        n_features=dataset["X_train"].shape[2],
        device=device,
        activation=activation,
    )

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

    preds_scaled = predict(model, dataset["X_test"], device)
    preds = inverse_transform_close(preds_scaled, dataset["close_scaler"])
    actuals = inverse_transform_close(dataset["y_test"], dataset["close_scaler"])

    metrics = compute_metrics(actuals, preds)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Train on assets listed in a names CSV/text file")
    parser.add_argument("--file", type=str, default="data.csv", help="Path to names file")
    parser.add_argument("--model", type=str, default="lstm", choices=["feedforward", "rnn", "lstm", "gru", "cnn", "hybrid"])
    parser.add_argument("--activation", type=str, default="relu", choices=["relu", "sigmoid", "tanh"])
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--lookback", type=int, default=20)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--max-assets", type=int, default=3, help="Train only first N mapped assets")
    args = parser.parse_args()

    names = load_names(Path(args.file))
    tickers, unresolved = to_tickers(names)

    if not tickers:
        raise ValueError("No recognized asset/company names were mapped to tickers.")

    selected = tickers[: max(1, args.max_assets)]

    print(f"Mapped tickers ({len(tickers)}): {tickers[:10]}{'...' if len(tickers) > 10 else ''}")
    if unresolved:
        print(f"Unresolved names ({len(unresolved)}): {unresolved[:10]}{'...' if len(unresolved) > 10 else ''}")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")

    all_metrics: dict[str, dict] = {}
    for ticker in selected:
        print("\n" + "=" * 60)
        print(f"Training {ticker}")
        print("=" * 60)
        try:
            metrics = train_one(
                ticker=ticker,
                model_type=args.model,
                activation=args.activation,
                epochs=args.epochs,
                lookback=args.lookback,
                lr=args.lr,
                batch_size=args.batch_size,
                device=device,
            )
            all_metrics[ticker] = metrics
            print(f"MAE={metrics['MAE']:.2f} RMSE={metrics['RMSE']:.2f} R2={metrics['R²']:.4f} MAPE={metrics['MAPE (%)']:.2f}%")
        except Exception as ex:
            print(f"Failed on {ticker}: {ex}")

    print("\nSummary")
    print("-" * 60)
    if not all_metrics:
        print("No assets were successfully trained.")
        return

    for ticker, m in all_metrics.items():
        print(f"{ticker:<12} MAE={m['MAE']:.2f} RMSE={m['RMSE']:.2f} R2={m['R²']:.4f} MAPE={m['MAPE (%)']:.2f}%")


if __name__ == "__main__":
    main()
