"""
Prediction and visualization module.

Generates predictions, computes evaluation metrics, and creates
publication-quality plots for model performance analysis.
"""

import os
import numpy as np
import torch
import torch.nn as nn
import matplotlib

_configured_backend = os.getenv("MATPLOTLIB_BACKEND", "").strip()
if _configured_backend:
    matplotlib.use(_configured_backend)
elif not os.getenv("DISPLAY"):
    matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from preprocessing import inverse_transform_close


def predict(
    model: nn.Module,
    X: np.ndarray,
    device: torch.device,
) -> np.ndarray:
    """Run inference and return predictions as a numpy array."""
    model.eval()
    with torch.no_grad():
        X_tensor = torch.tensor(X, dtype=torch.float32).to(device)
        preds = model(X_tensor).cpu().numpy()
    return preds


def inverse_transform_predictions(
    preds: np.ndarray,
    actuals: np.ndarray,
    close_scaler,
) -> tuple[np.ndarray, np.ndarray]:
    """Convert normalized predictions/actuals back to original price scale."""
    preds_price = inverse_transform_close(preds, close_scaler)
    actuals_price = inverse_transform_close(actuals, close_scaler)
    return preds_price, actuals_price


def compute_metrics(actuals: np.ndarray, predictions: np.ndarray) -> dict:
    """Compute regression and direction metrics."""
    errors = actuals - predictions
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(errors ** 2)))
    ss_res = float(np.sum(errors ** 2))
    ss_tot = float(np.sum((actuals - np.mean(actuals)) ** 2))
    r2 = 1.0 - (ss_res / (ss_tot + 1e-12))
    mape = np.mean(np.abs((actuals - predictions) / (actuals + 1e-8))) * 100

    if len(actuals) > 1:
        actual_dir = np.sign(np.diff(actuals))
        pred_dir = np.sign(np.diff(predictions))
        direction_acc = float(np.mean(actual_dir == pred_dir) * 100.0)
    else:
        direction_acc = 0.0

    return {
        "MAE": mae,
        "RMSE": rmse,
        "R²": float(r2),
        "MAPE (%)": float(mape),
        "Direction Accuracy (%)": direction_acc,
    }


def plot_training_history(history: dict, ticker: str, model_name: str, save_path: str | None = None):
    """Plot training and validation loss curves."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    epochs = range(1, len(history["train_loss"]) + 1)
    ax1.plot(
        epochs,
        history["train_loss"],
        label="Train Loss",
        color="#2196F3",
        linewidth=1.5,
        marker="o",
        markersize=5,
    )
    ax1.plot(
        epochs,
        history["val_loss"],
        label="Val Loss",
        color="#F44336",
        linewidth=1.5,
        marker="o",
        markersize=5,
    )
    ax1.set_xlabel("Epoch")
    ax1.set_ylabel("MSE Loss")
    ax1.set_title(f"{ticker} — {model_name} Training Curves")
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    ax1.set_yscale("log")

    ax2.plot(epochs, history["lr"], color="#4CAF50", linewidth=1.5, marker="o", markersize=5)
    ax2.set_xlabel("Epoch")
    ax2.set_ylabel("Learning Rate")
    ax2.set_title("Learning Rate Schedule")
    ax2.grid(True, alpha=0.3)

    if len(history["train_loss"]) == 1:
        ax1.set_xlim(0.5, 1.5)
        ax2.set_xlim(0.5, 1.5)

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"  Saved: {save_path}")
    plt.close()


def plot_predictions(
    actuals: np.ndarray,
    predictions: np.ndarray,
    ticker: str,
    model_name: str,
    dates=None,
    save_path: str | None = None,
):
    """Plot actual vs predicted prices."""
    fig, axes = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={"height_ratios": [3, 1]})

    x_axis = dates if dates is not None else range(len(actuals))

    # Price comparison
    ax = axes[0]
    ax.plot(x_axis, actuals, label="Actual Price", color="#2196F3", linewidth=1.2, alpha=0.9)
    ax.plot(x_axis, predictions, label="Predicted Price", color="#F44336", linewidth=1.2, alpha=0.9)
    ax.fill_between(
        x_axis, actuals, predictions,
        alpha=0.15, color="gray", label="Error Band",
    )
    ax.set_ylabel("Price ($)")
    ax.set_title(f"{ticker} — {model_name} Price Prediction")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)

    if dates is not None:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)

    # Prediction error
    ax2 = axes[1]
    errors = actuals - predictions
    ax2.bar(x_axis, errors, color=np.where(errors >= 0, "#4CAF50", "#F44336"), alpha=0.7, width=1)
    ax2.axhline(y=0, color="black", linewidth=0.5)
    ax2.set_ylabel("Error ($)")
    ax2.set_xlabel("Date" if dates is not None else "Time Step")
    ax2.set_title("Prediction Error (Actual - Predicted)")
    ax2.grid(True, alpha=0.3)

    if dates is not None:
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45)

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"  Saved: {save_path}")
    plt.close()


def plot_model_comparison(results: dict, save_path: str | None = None):
    """
    Bar chart comparing metrics across models.

    Args:
        results: {model_name: {metric_name: value, ...}, ...}
    """
    model_names = list(results.keys())
    metrics = ["MAE", "RMSE", "MAPE (%)"]

    fig, axes = plt.subplots(1, len(metrics), figsize=(5 * len(metrics), 5))
    colors = ["#2196F3", "#F44336", "#4CAF50", "#FF9800"]

    for i, metric in enumerate(metrics):
        values = [results[m][metric] for m in model_names]
        bars = axes[i].bar(model_names, values, color=colors[: len(model_names)], alpha=0.8)
        axes[i].set_title(metric)
        axes[i].grid(True, alpha=0.3, axis="y")
        for bar, val in zip(bars, values):
            axes[i].text(
                bar.get_x() + bar.get_width() / 2, bar.get_height(),
                f"{val:.2f}", ha="center", va="bottom", fontsize=9,
            )

    plt.suptitle("Model Comparison", fontsize=14, fontweight="bold")
    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"  Saved: {save_path}")
    plt.close()


def print_metrics(metrics: dict, ticker: str, model_name: str):
    """Pretty-print evaluation metrics."""
    print(f"\n  ┌── {ticker} | {model_name} ──────────────────┐")
    for name, value in metrics.items():
        print(f"  │  {name:<10}: {value:>10.4f}             │")
    print(f"  └─────────────────────────────────────────┘")
