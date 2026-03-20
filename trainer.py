"""
Training pipeline for price prediction models.

Implements the optimization framework from Jentzen et al. (2023):

- **Empirical Risk Minimization** (Chapter 3): We minimize the empirical
  risk L(θ) = (1/N) Σ ℓ(f_θ(x_i), y_i) over the training set.

- **Stochastic Gradient Descent (SGD)** variants (Chapter 5):
  The PDF covers gradient descent extensively (Sections 5.1–5.7).
  We use Adam optimizer, a variant of SGD with adaptive learning rates
  that combines momentum (Section 5.5) with RMSProp-style scaling.

- **Learning Rate Scheduling**: Reduces learning rate on plateau,
  related to the step-size analysis in Section 5.3.

- **Loss Functions** (12+ variants):
  Classical: MSE (L²), MAE (L¹), Huber, RMSE
  Robust to outliers: LogCosh
  Quantile-based: Quantile, Pinball (directional asymmetric loss)
  Financial: DirectionWeighted (buy/sell emphasis), SymmetricMAPE, ReturnVolatility
  Advanced: HuberLogCombined, AdaptiveWeighted (sample difficulty weighting)
  
  Use production_hardening.loss_functions.get_loss_function() for extensibility.
"""

import time
import gc
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from production_hardening.loss_functions import get_loss_function


class EarlyStopping:
    """Stop training when validation loss stops improving."""

    def __init__(self, patience: int = 15, min_delta: float = 1e-6):
        self.patience = patience
        self.min_delta = min_delta
        self.counter = 0
        self.best_loss = float("inf")
        self.should_stop = False

    def step(self, val_loss: float) -> bool:
        if val_loss < self.best_loss - self.min_delta:
            self.best_loss = val_loss
            self.counter = 0
        else:
            self.counter += 1
            if self.counter >= self.patience:
                self.should_stop = True
        return self.should_stop


def train_model(
    model: nn.Module,
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_test: np.ndarray,
    y_test: np.ndarray,
    device: torch.device,
    epochs: int = 100,
    batch_size: int = 64,
    learning_rate: float = 1e-3,
    weight_decay: float = 1e-5,
    patience: int = 15,
    optimizer_name: str = "adam",
    loss_name: str = "mse",
) -> dict:
    """
    Train a model using Adam (SGD with adaptive learning rates).

    The optimization follows the gradient descent framework from Chapter 5:
        θ_{n+1} = θ_n - γ_n ∇L(θ_n)
    where γ_n is the learning rate and ∇L is the gradient of the loss.

    Adam extends this with first/second moment estimates (cf. Section 5.5
    on momentum-based methods).

    Args:
        model: Neural network to train.
        X_train, y_train: Training data (numpy arrays).
        X_test, y_test: Validation data (numpy arrays).
        device: Torch device.
        epochs: Maximum training epochs.
        batch_size: Mini-batch size for SGD (Section 5.4).
        learning_rate: Initial step size γ (Section 5.3).
        weight_decay: L² regularization strength.
        patience: Early stopping patience.

    Returns:
        Dictionary with training history and best model state.
    """
    # Convert to tensors
    train_dataset = TensorDataset(
        torch.tensor(X_train, dtype=torch.float32),
        torch.tensor(y_train, dtype=torch.float32),
    )
    test_dataset = TensorDataset(
        torch.tensor(X_test, dtype=torch.float32),
        torch.tensor(y_test, dtype=torch.float32),
    )
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    test_loader = DataLoader(test_dataset, batch_size=batch_size, shuffle=False)

    # Initialize loss function using factory (supports 12+ loss variants)
    criterion = get_loss_function(loss_name)

    opt = optimizer_name.lower()
    if opt == "adam":
        optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
    elif opt == "sgd":
        optimizer = torch.optim.SGD(model.parameters(), lr=learning_rate, momentum=0.9, weight_decay=weight_decay)
    elif opt == "rmsprop":
        optimizer = torch.optim.RMSprop(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
    elif opt == "adagrad":
        optimizer = torch.optim.Adagrad(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
    else:
        raise ValueError("optimizer_name must be one of: adam, sgd, rmsprop, adagrad")

    # Reduce LR on plateau (relates to step-size analysis, Section 5.3)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="min", factor=0.5, patience=7
    )

    early_stopping = EarlyStopping(patience=patience)
    history = {"train_loss": [], "val_loss": [], "lr": []}
    best_state = None
    best_val_loss = float("inf")

    print(f"  Training on {device} | {sum(p.numel() for p in model.parameters()):,} parameters")
    print(f"  Optimizer: {opt.upper()} | Loss: {loss_name.upper()}")
    print(f"  {'Epoch':>6} {'Train Loss':>12} {'Val Loss':>12} {'LR':>12}")
    print(f"  {'─' * 46}")

    for epoch in range(1, epochs + 1):
        # ---- Training phase (SGD updates) ----
        model.train()
        train_losses = []
        for X_batch, y_batch in train_loader:
            X_batch, y_batch = X_batch.to(device), y_batch.to(device)
            optimizer.zero_grad()
            predictions = model(X_batch)
            loss = criterion(predictions, y_batch)
            loss.backward()       # Backpropagation (Section 5.6)
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()      # θ ← θ - γ ∇L(θ)
            train_losses.append(loss.item())

        # ---- Validation phase ----
        model.eval()
        val_losses = []
        with torch.no_grad():
            for X_batch, y_batch in test_loader:
                X_batch, y_batch = X_batch.to(device), y_batch.to(device)
                predictions = model(X_batch)
                val_losses.append(criterion(predictions, y_batch).item())

        train_loss = np.mean(train_losses)
        val_loss = np.mean(val_losses)
        current_lr = optimizer.param_groups[0]["lr"]

        history["train_loss"].append(train_loss)
        history["val_loss"].append(val_loss)
        history["lr"].append(current_lr)

        scheduler.step(val_loss)

        # Save best model
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

        if epoch % 10 == 0 or epoch == 1:
            print(f"  {epoch:>6} {train_loss:>12.6f} {val_loss:>12.6f} {current_lr:>12.2e}")

        if early_stopping.step(val_loss):
            print(f"  Early stopping at epoch {epoch}")
            break

    # Restore best model
    if best_state is not None:
        model.load_state_dict(best_state)
        model.to(device)

    # Explicit cleanup to prevent GPU memory accumulation across repeated runs.
    del train_dataset, test_dataset, train_loader, test_loader
    gc.collect()
    if device.type == "cuda":
        torch.cuda.empty_cache()

    print(f"  Best validation loss: {best_val_loss:.6f}")
    return history
