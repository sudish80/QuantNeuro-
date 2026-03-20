"""Data preprocessing and feature engineering algorithms for market time series."""

import numpy as np
import pandas as pd


FEATURE_COLUMNS = [
    "Close",
    "Volume",
    "Returns",
    "Log_Returns",
    "MA_20",
    "EMA_20",
    "RSI_14",
    "MACD",
    "MACD_Signal",
    "Bollinger_Upper",
    "Bollinger_Lower",
    "ATR_14",
    "Volatility",
    "High_Low_Spread",
    "Close_Open_Spread",
]


def impute_missing_values(df: pd.DataFrame) -> pd.DataFrame:
    """Fill missing values using forward-fill, backward-fill, then median."""
    out = df.copy()
    out = out.ffill().bfill()
    for col in out.columns:
        if out[col].isna().any():
            out[col] = out[col].fillna(out[col].median())
    return out


def clip_outliers_iqr(df: pd.DataFrame, cols: list[str], factor: float = 1.5) -> pd.DataFrame:
    """IQR-based outlier clipping."""
    out = df.copy()
    for col in cols:
        if col not in out.columns:
            continue
        q1 = out[col].quantile(0.25)
        q3 = out[col].quantile(0.75)
        iqr = q3 - q1
        lower = q1 - factor * iqr
        upper = q3 + factor * iqr
        out[col] = out[col].clip(lower, upper)
    return out


def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add MA, EMA, RSI, MACD, Bollinger Bands, ATR, and log returns."""
    out = df.copy()

    out["Returns"] = out["Close"].pct_change()
    out["Log_Returns"] = np.log(out["Close"] / out["Close"].shift(1))
    out["MA_20"] = out["Close"].rolling(window=20).mean()
    out["EMA_20"] = out["Close"].ewm(span=20, adjust=False).mean()

    delta = out["Close"].diff()
    gain = delta.clip(lower=0).rolling(window=14).mean()
    loss = (-delta.clip(upper=0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-12)
    out["RSI_14"] = 100 - (100 / (1 + rs))

    ema12 = out["Close"].ewm(span=12, adjust=False).mean()
    ema26 = out["Close"].ewm(span=26, adjust=False).mean()
    out["MACD"] = ema12 - ema26
    out["MACD_Signal"] = out["MACD"].ewm(span=9, adjust=False).mean()

    std20 = out["Close"].rolling(window=20).std()
    out["Bollinger_Upper"] = out["MA_20"] + 2 * std20
    out["Bollinger_Lower"] = out["MA_20"] - 2 * std20

    prev_close = out["Close"].shift(1)
    tr1 = out["High"] - out["Low"]
    tr2 = (out["High"] - prev_close).abs()
    tr3 = (out["Low"] - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    out["ATR_14"] = true_range.rolling(window=14).mean()

    out["Volatility"] = out["Returns"].rolling(window=20).std()
    out["High_Low_Spread"] = (out["High"] - out["Low"]) / (out["Close"] + 1e-12)
    out["Close_Open_Spread"] = (out["Close"] - out["Open"]) / (out["Open"] + 1e-12)
    return out


def normalize_features(data: np.ndarray, mode: str = "minmax") -> tuple[np.ndarray, dict]:
    """Normalize feature matrix with min-max or z-score scaling."""
    if mode == "minmax":
        mins = data.min(axis=0)
        maxs = data.max(axis=0)
        denom = np.where((maxs - mins) == 0, 1.0, maxs - mins)
        scaled = (data - mins) / denom
        params = {"mode": "minmax", "mins": mins, "maxs": maxs}
        return scaled, params

    if mode == "zscore":
        means = data.mean(axis=0)
        stds = data.std(axis=0)
        stds = np.where(stds == 0, 1.0, stds)
        scaled = (data - means) / stds
        params = {"mode": "zscore", "means": means, "stds": stds}
        return scaled, params

    raise ValueError("normalization must be one of: minmax, zscore")


def apply_normalization(data: np.ndarray, params: dict) -> np.ndarray:
    """Apply previously-fitted normalization params to any feature matrix."""
    mode = params["mode"]
    if mode == "minmax":
        mins = params["mins"]
        maxs = params["maxs"]
        denom = np.where((maxs - mins) == 0, 1.0, maxs - mins)
        return (data - mins) / denom
    if mode == "zscore":
        means = params["means"]
        stds = np.where(params["stds"] == 0, 1.0, params["stds"])
        return (data - means) / stds
    raise ValueError("normalization must be one of: minmax, zscore")


def inverse_transform_close(values: np.ndarray, close_stats: dict) -> np.ndarray:
    """Inverse-transform normalized close values back to price scale."""
    if close_stats["mode"] == "minmax":
        return values * (close_stats["max"] - close_stats["min"]) + close_stats["min"]
    return values * close_stats["std"] + close_stats["mean"]


def create_windows(
    scaled_data: np.ndarray,
    close_idx: int,
    lookback: int,
    forecast_horizon: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Sliding-window algorithm for sequence-to-one prediction."""
    X, y = [], []
    for i in range(lookback, len(scaled_data) - forecast_horizon + 1):
        X.append(scaled_data[i - lookback : i])
        y.append(scaled_data[i + forecast_horizon - 1, close_idx])
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32)


def prepare_dataset(
    df: pd.DataFrame,
    lookback: int = 60,
    forecast_horizon: int = 1,
    feature_cols: list[str] | None = None,
    train_ratio: float = 0.8,
    normalization: str = "minmax",
) -> dict:
    """End-to-end preprocessing with cleaning, features, scaling, and windowing."""
    if feature_cols is None:
        feature_cols = FEATURE_COLUMNS

    enriched = add_technical_indicators(df)
    enriched = impute_missing_values(enriched)
    enriched = clip_outliers_iqr(enriched, ["Close", "Volume", "Returns", "Log_Returns"])
    enriched = enriched.dropna().copy()

    available = [c for c in feature_cols if c in enriched.columns]
    if "Close" not in available:
        raise ValueError("'Close' must exist in feature columns")

    data = enriched[available].values.astype(np.float64)

    # Fit scaler on train segment only to prevent train-test leakage.
    split_row = int(len(data) * train_ratio)
    if split_row <= 1 or split_row >= len(data):
        raise ValueError("train_ratio results in an invalid train/test split")
    train_data = data[:split_row]
    _, scaler_params = normalize_features(train_data, mode=normalization)
    scaled_data = apply_normalization(data, scaler_params)

    close_idx = available.index("Close")
    if normalization == "minmax":
        close_stats = {
            "mode": "minmax",
            "min": scaler_params["mins"][close_idx],
            "max": scaler_params["maxs"][close_idx],
        }
    else:
        close_stats = {
            "mode": "zscore",
            "mean": scaler_params["means"][close_idx],
            "std": scaler_params["stds"][close_idx],
        }

    X, y = create_windows(
        scaled_data=scaled_data,
        close_idx=close_idx,
        lookback=lookback,
        forecast_horizon=forecast_horizon,
    )

    split = max(0, split_row - lookback - forecast_horizon + 1)
    return {
        "X_train": X[:split],
        "y_train": y[:split],
        "X_test": X[split:],
        "y_test": y[split:],
        "scaler_params": scaler_params,
        "close_scaler": close_stats,
        "feature_cols": available,
        "lookback": lookback,
        "processed_df": enriched,
    }
