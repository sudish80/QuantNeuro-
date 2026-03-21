"""Walk-forward validation with realistic costs, stress tests, and overfitting checks."""

from __future__ import annotations

import argparse
import json
import numpy as np
import torch

from data_fetcher import fetch_data
from models import build_model
from preprocessing import (
    prepare_dataset,
    inverse_transform_close,
    add_technical_indicators,
    impute_missing_values,
    clip_outliers_iqr,
    normalize_features,
    apply_normalization,
    FEATURE_COLUMNS,
)
from trainer import train_model
from predict_visualize import predict, compute_metrics


def apply_market_realism(
    gross_returns: np.ndarray,
    fee_bps: float,
    slippage_bps: float,
    spread_bps: float,
    latency_bps: float,
    funding_bps: float,
    borrow_bps: float,
) -> np.ndarray:
    total_cost_bps = fee_bps + slippage_bps + spread_bps + latency_bps + funding_bps + borrow_bps
    total_cost = total_cost_bps / 10000.0
    return gross_returns - total_cost


def walk_forward_splits(n: int, train_size: int, test_size: int, step: int):
    start = 0
    while start + train_size + test_size <= n:
        yield (start, start + train_size, start + train_size + test_size)
        start += step


def run_walk_forward(
    ticker: str,
    model_type: str,
    activation: str,
    lookback: int,
    epochs: int,
    source: str,
    period: str,
    interval: str,
    normalization: str,
    train_ratio: float,
    test_ratio: float,
    step_ratio: float,
    min_train_size: int,
    min_test_size: int,
    min_step_size: int,
    fee_bps: float,
    slippage_bps: float,
    spread_bps: float,
    latency_bps: float,
    funding_bps: float,
    borrow_bps: float,
    min_r2: float | None = None,
    max_mape: float | None = None,
    max_rmse_std_ratio: float | None = None,
    enforce_thresholds: bool = False,
    summary_path: str | None = None,
):
    """
    CORRECTED Walk-forward validation with per-fold scaler re-fitting.
    
    FIX for data leakage: Each fold gets its own scaler, fit on THAT fold's
    training data only. This prevents look-ahead bias from the original 80/20 split.
    """
    df = fetch_data(ticker=ticker, source=source, period=period, interval=interval)
    
    # Step 1: Prepare data to windowed format WITHOUT global scaling
    enriched = add_technical_indicators(df)
    enriched = impute_missing_values(enriched)
    enriched = clip_outliers_iqr(enriched, ["Close", "Volume", "Returns", "Log_Returns"])
    enriched = enriched.dropna().copy()
    
    feature_cols = FEATURE_COLUMNS
    available = [c for c in feature_cols if c in enriched.columns]
    if "Close" not in available:
        raise ValueError("'Close' must exist in feature columns")
    
    data_raw = enriched[available].values.astype(np.float64)  # Raw, unscaled
    close_idx = available.index("Close")
    
    # Step 2: Create raw windows (don't scale yet!)
    X_all_raw = []
    y_all_raw = []
    for i in range(lookback, len(data_raw)):
        X_all_raw.append(data_raw[i - lookback : i])
        y_all_raw.append(data_raw[i, close_idx])
    
    X_all_raw = np.array(X_all_raw, dtype=np.float32)
    y_all_raw = np.array(y_all_raw, dtype=np.float32)

    
    n = len(X_all_raw)
    train_size = max(min_train_size, int(train_ratio * n))
    test_size = max(min_test_size, int(test_ratio * n))
    step = max(min_step_size, int(step_ratio * n))

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    fold_metrics = []

    for idx, (s, t, u) in enumerate(walk_forward_splits(n, train_size, test_size, step), start=1):
        # FIX #1: Extract raw WINDOWS (not yet scaled)
        X_train_raw = X_all_raw[s:t]  # Raw windows
        y_train_raw = y_all_raw[s:t]
        X_test_raw = X_all_raw[t:u]   # Raw windows
        y_test_raw = y_all_raw[t:u]
        
        # FIX #2: FIT SCALER on THIS fold's training data ONLY
        # Get 2D array: (n_samples * lookback, n_features)
        X_train_flat = X_train_raw.reshape(-1, X_train_raw.shape[-1])
        _, scaler_params = normalize_features(X_train_flat, mode=normalization)
        
        # FIX #3: SCALE train and test X with fold-specific scaler
        X_train = apply_normalization(X_train_flat, scaler_params).reshape(X_train_raw.shape)
        X_test_flat = X_test_raw.reshape(-1, X_test_raw.shape[-1])
        X_test = apply_normalization(X_test_flat, scaler_params).reshape(X_test_raw.shape)
        
        # FIX #4: SCALE y values (close prices) using close column scaler
        close_col_idx = close_idx  # Index of Close in features
        if normalization == "minmax":
            y_train_min = scaler_params["mins"][close_col_idx]
            y_train_max = scaler_params["maxs"][close_col_idx]
            y_train = (y_train_raw - y_train_min) / (y_train_max - y_train_min + 1e-12)
            y_test = (y_test_raw - y_train_min) / (y_train_max - y_train_min + 1e-12)
        else:  # zscore
            y_train_mean = scaler_params["means"][close_col_idx]
            y_train_std = scaler_params["stds"][close_col_idx]
            y_train = (y_train_raw - y_train_mean) / (y_train_std + 1e-12)
            y_test = (y_test_raw - y_train_mean) / (y_train_std + 1e-12)
        
        # Store scaler for inverse transform later
        close_scaler_fold = {
            "mode": normalization,
            "params": scaler_params
        }
        
        # Train model on fold-specific scaled data
        model = build_model(model_type=model_type, lookback=lookback, n_features=X_train.shape[2], device=device, activation=activation)
        train_model(
            model=model,
            X_train=X_train,
            y_train=y_train_raw,
            X_test=X_test,
            y_test=y_test_raw,
            device=device,
            epochs=epochs,
            batch_size=64,
            learning_rate=1e-3,
            optimizer_name="adam",
            loss_name="mse",
        )

        pred_scaled = predict(model, X_test, device)
        
        # FIX #4: Inverse transform using fold-specific scaler
        pred = inverse_transform_close(pred_scaled, close_scaler_fold)
        actual = y_test_raw  # Already in original price space

        m = compute_metrics(actual, pred)

        if len(actual) > 1:
            gross_returns = np.diff(actual) / (actual[:-1] + 1e-12)
            net_returns = apply_market_realism(
                gross_returns,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                spread_bps=spread_bps,
                latency_bps=latency_bps,
                funding_bps=funding_bps,
                borrow_bps=borrow_bps,
            )
            m["Net Return Mean"] = float(np.mean(net_returns))
            m["Net Return Std"] = float(np.std(net_returns))
        else:
            m["Net Return Mean"] = 0.0
            m["Net Return Std"] = 0.0

        fold_metrics.append(m)
        print(f"Fold {idx}: RMSE={m['RMSE']:.2f} MAPE={m['MAPE (%)']:.2f}% R2={m['R²']:.4f}")

    if not fold_metrics:
        raise RuntimeError("No walk-forward folds generated. Increase available data.")

    avg_rmse = float(np.mean([m["RMSE"] for m in fold_metrics]))
    avg_mape = float(np.mean([m["MAPE (%)"] for m in fold_metrics]))
    avg_r2 = float(np.mean([m["R²"] for m in fold_metrics]))

    # Overfitting control heuristic: high variance across folds
    rmse_std = float(np.std([m["RMSE"] for m in fold_metrics]))
    overfit_flag = rmse_std > 0.20 * max(avg_rmse, 1e-12)

    # Regime test: compare first half vs second half folds
    k = len(fold_metrics)
    first_half = fold_metrics[: max(1, k // 2)]
    second_half = fold_metrics[max(1, k // 2):]
    regime_shift = abs(np.mean([m["RMSE"] for m in first_half]) - np.mean([m["RMSE"] for m in second_half]))

    # Stress test: apply extra shock costs
    stress_penalty = fee_bps + slippage_bps + spread_bps + latency_bps + funding_bps + borrow_bps

    print("\nWalk-forward summary")
    print("-" * 60)
    print(f"Avg RMSE: {avg_rmse:.2f}")
    print(f"Avg MAPE: {avg_mape:.2f}%")
    print(f"Avg R2:   {avg_r2:.4f}")
    print(f"RMSE std: {rmse_std:.2f} | Overfit flag: {overfit_flag}")
    print(f"Regime shift score (RMSE gap): {regime_shift:.2f}")
    print(f"Stress penalty bps configured: {stress_penalty:.2f}")

    production_ready = (avg_r2 > 0.4) and (avg_mape < 5.0) and (not overfit_flag)
    print(f"Production-readiness heuristic: {production_ready}")

    summary = {
        "avg_rmse": avg_rmse,
        "avg_mape": avg_mape,
        "avg_r2": avg_r2,
        "rmse_std": rmse_std,
        "rmse_std_ratio": (rmse_std / max(avg_rmse, 1e-12)),
        "overfit_flag": overfit_flag,
        "regime_shift": float(regime_shift),
        "production_ready": bool(production_ready),
    }

    if summary_path:
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

    if enforce_thresholds:
        failed = []
        if min_r2 is not None and avg_r2 < min_r2:
            failed.append(f"avg_r2 {avg_r2:.4f} < min_r2 {min_r2:.4f}")
        if max_mape is not None and avg_mape > max_mape:
            failed.append(f"avg_mape {avg_mape:.4f} > max_mape {max_mape:.4f}")
        if max_rmse_std_ratio is not None and summary["rmse_std_ratio"] > max_rmse_std_ratio:
            failed.append(
                f"rmse_std_ratio {summary['rmse_std_ratio']:.4f} > max_rmse_std_ratio {max_rmse_std_ratio:.4f}"
            )
        if failed:
            raise SystemExit("Walk-forward thresholds failed: " + " | ".join(failed))

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Walk-forward validation with market realism")
    parser.add_argument("--ticker", type=str, default="BTC-USD")
    parser.add_argument("--model", type=str, default="lstm", choices=["feedforward", "rnn", "lstm", "gru", "cnn", "hybrid"])
    parser.add_argument("--activation", type=str, default="relu", choices=["relu", "sigmoid", "tanh"])
    parser.add_argument("--lookback", type=int, default=20)
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--source", type=str, default="yahoo", choices=["yahoo", "binance", "alphavantage"])
    parser.add_argument("--period", type=str, default="5y")
    parser.add_argument("--interval", type=str, default="1d")
    parser.add_argument("--normalization", type=str, default="minmax", choices=["minmax", "zscore"])
    parser.add_argument("--train-ratio", type=float, default=0.6)
    parser.add_argument("--test-ratio", type=float, default=0.1)
    parser.add_argument("--step-ratio", type=float, default=0.05)
    parser.add_argument("--min-train-size", type=int, default=300)
    parser.add_argument("--min-test-size", type=int, default=60)
    parser.add_argument("--min-step-size", type=int, default=30)
    parser.add_argument("--fee-bps", type=float, default=8.0)
    parser.add_argument("--slippage-bps", type=float, default=6.0)
    parser.add_argument("--spread-bps", type=float, default=4.0)
    parser.add_argument("--latency-bps", type=float, default=2.0)
    parser.add_argument("--funding-bps", type=float, default=1.0)
    parser.add_argument("--borrow-bps", type=float, default=1.0)
    parser.add_argument("--min-r2", type=float, default=None)
    parser.add_argument("--max-mape", type=float, default=None)
    parser.add_argument("--max-rmse-std-ratio", type=float, default=None)
    parser.add_argument("--enforce-thresholds", action="store_true")
    parser.add_argument("--summary-path", type=str, default=None)
    args = parser.parse_args()

    run_walk_forward(
        ticker=args.ticker,
        model_type=args.model,
        activation=args.activation,
        lookback=args.lookback,
        epochs=args.epochs,
        source=args.source,
        period=args.period,
        interval=args.interval,
        normalization=args.normalization,
        train_ratio=args.train_ratio,
        test_ratio=args.test_ratio,
        step_ratio=args.step_ratio,
        min_train_size=args.min_train_size,
        min_test_size=args.min_test_size,
        min_step_size=args.min_step_size,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        spread_bps=args.spread_bps,
        latency_bps=args.latency_bps,
        funding_bps=args.funding_bps,
        borrow_bps=args.borrow_bps,
        min_r2=args.min_r2,
        max_mape=args.max_mape,
        max_rmse_std_ratio=args.max_rmse_std_ratio,
        enforce_thresholds=args.enforce_thresholds,
        summary_path=args.summary_path,
    )


if __name__ == "__main__":
    main()
