"""
Neural network models for price prediction.

Implements architectures grounded in the mathematical framework from
"Mathematical Introduction to Deep Learning" (Jentzen et al., 2023):

1. **FeedforwardNet** — A fully connected deep network (Chapter 2–3):
   Realizes f_θ : ℝ^d → ℝ as a composition of affine transformations
   and multidimensional activation functions:
       f_θ = A_L ∘ 𝔸_{a_{L-1}} ∘ A_{L-1} ∘ … ∘ 𝔸_{a_1} ∘ A_1
   where A_k(x) = W_k x + b_k (Definition 2.1.1) and 𝔸_a applies
   activation a : ℝ → ℝ componentwise (Definition 2.1.2).

2. **LSTMNet** — An LSTM recurrent network for sequential data,
   extended from the feedforward framework with gating mechanisms.

3. **HybridNet** — Combines LSTM feature extraction with a deep
   feedforward head, leveraging both temporal patterns and the
   universal approximation capacity of deep ReLU networks (Chapter 4).

All models use:
- ReLU activation (Definition 2.3.1): max(x, 0), the standard
  rectifier shown to enable universal approximation (Theorem 4.2.1).
- Xavier/Glorot initialization for weight matrices.
- Dropout regularization to reduce overfitting.
"""

import torch
import torch.nn as nn


def get_activation(name: str) -> nn.Module:
    """Return activation module by name."""
    key = name.lower()
    if key == "relu":
        return nn.ReLU()
    if key == "sigmoid":
        return nn.Sigmoid()
    if key == "tanh":
        return nn.Tanh()
    raise ValueError("activation must be one of: relu, sigmoid, tanh")


class FeedforwardNet(nn.Module):
    """
    Deep feedforward (fully connected) network.

    Architecture follows Definition 2.1.3 — a realization of a
    deep neural network with L hidden layers:
        ℝ^{l_0} → ℝ^{l_1} → … → ℝ^{l_L} → ℝ^1

    Uses ReLU activations between hidden layers (Definition 2.3.1)
    and a linear output for regression.
    """

    def __init__(
        self,
        input_dim: int,
        hidden_dims: list[int] | None = None,
        dropout: float = 0.2,
        activation: str = "relu",
    ):
        super().__init__()
        if hidden_dims is None:
            hidden_dims = [256, 128, 64, 32]

        layers = []
        prev_dim = input_dim
        for h_dim in hidden_dims:
            layers.append(nn.Linear(prev_dim, h_dim))
            layers.append(get_activation(activation))
            layers.append(nn.BatchNorm1d(h_dim))
            layers.append(nn.Dropout(dropout))
            prev_dim = h_dim

        layers.append(nn.Linear(prev_dim, 1))  # Output layer — scalar prediction
        self.network = nn.Sequential(*layers)
        self._init_weights()

    def _init_weights(self):
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)
                nn.init.zeros_(m.bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Flatten the lookback window: (batch, lookback, features) → (batch, lookback*features)
        x = x.reshape(x.size(0), -1)
        return self.network(x).squeeze(-1)


class LSTMNet(nn.Module):
    """
    LSTM-based recurrent network for sequential price data.

    Extends the feedforward framework with learned gating to handle
    temporal dependencies in financial time series. The final hidden
    state is passed through a feedforward head (Section 2.1).
    """

    def __init__(
        self,
        input_features: int,
        hidden_size: int = 128,
        num_layers: int = 2,
        dropout: float = 0.2,
        activation: str = "relu",
    ):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_features,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        # Feedforward head after LSTM (Def 2.1.3)
        self.head = nn.Sequential(
            nn.Linear(hidden_size, 64),
            get_activation(activation),
            nn.Dropout(dropout),
            nn.Linear(64, 1),
        )
        self._init_weights()

    def _init_weights(self):
        for name, param in self.lstm.named_parameters():
            if "weight_ih" in name:
                nn.init.xavier_uniform_(param)
            elif "weight_hh" in name:
                nn.init.orthogonal_(param)
            elif "bias" in name:
                nn.init.zeros_(param)
        for m in self.head.modules():
            if isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)
                nn.init.zeros_(m.bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x shape: (batch, lookback, features)
        lstm_out, _ = self.lstm(x)
        last_hidden = lstm_out[:, -1, :]  # Take last time step
        return self.head(last_hidden).squeeze(-1)


class RNNNet(nn.Module):
    """Vanilla RNN for sequence regression."""

    def __init__(
        self,
        input_features: int,
        hidden_size: int = 128,
        num_layers: int = 2,
        dropout: float = 0.2,
        activation: str = "relu",
    ):
        super().__init__()
        recurrent_nonlinearity = "relu" if activation.lower() == "relu" else "tanh"
        self.rnn = nn.RNN(
            input_size=input_features,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            nonlinearity=recurrent_nonlinearity,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.head = nn.Sequential(
            nn.Linear(hidden_size, 64),
            get_activation(activation),
            nn.Dropout(dropout),
            nn.Linear(64, 1),
        )
        self._init_weights()

    def _init_weights(self):
        for name, param in self.rnn.named_parameters():
            if "weight_ih" in name or "weight_hh" in name:
                nn.init.xavier_uniform_(param)
            elif "bias" in name:
                nn.init.zeros_(param)
        for m in self.head.modules():
            if isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)
                nn.init.zeros_(m.bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.rnn(x)
        return self.head(out[:, -1, :]).squeeze(-1)


class GRUNet(nn.Module):
    """GRU model for efficient sequence learning."""

    def __init__(
        self,
        input_features: int,
        hidden_size: int = 128,
        num_layers: int = 2,
        dropout: float = 0.2,
        activation: str = "relu",
    ):
        super().__init__()
        self.gru = nn.GRU(
            input_size=input_features,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.head = nn.Sequential(
            nn.Linear(hidden_size, 64),
            get_activation(activation),
            nn.Dropout(dropout),
            nn.Linear(64, 1),
        )
        self._init_weights()

    def _init_weights(self):
        for name, param in self.gru.named_parameters():
            if "weight_ih" in name:
                nn.init.xavier_uniform_(param)
            elif "weight_hh" in name:
                nn.init.orthogonal_(param)
            elif "bias" in name:
                nn.init.zeros_(param)
        for m in self.head.modules():
            if isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)
                nn.init.zeros_(m.bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.gru(x)
        return self.head(out[:, -1, :]).squeeze(-1)


class CNN1DNet(nn.Module):
    """1D CNN over time axis for local pattern extraction."""

    def __init__(self, input_features: int, dropout: float = 0.2, activation: str = "relu"):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv1d(input_features, 64, kernel_size=3, padding=1),
            get_activation(activation),
            nn.Conv1d(64, 128, kernel_size=3, padding=1),
            get_activation(activation),
            nn.AdaptiveAvgPool1d(1),
        )
        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Linear(128, 64),
            get_activation(activation),
            nn.Dropout(dropout),
            nn.Linear(64, 1),
        )
        self._init_weights()

    def _init_weights(self):
        for m in self.modules():
            if isinstance(m, (nn.Linear, nn.Conv1d)):
                nn.init.xavier_uniform_(m.weight)
                if m.bias is not None:
                    nn.init.zeros_(m.bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # (batch, seq, feat) -> (batch, feat, seq)
        x = x.transpose(1, 2)
        x = self.features(x)
        return self.head(x).squeeze(-1)


class HybridNet(nn.Module):
    """
    Hybrid LSTM + Feedforward network.

    Combines LSTM temporal feature extraction with a deep feedforward
    classifier, leveraging:
    - LSTM layers to capture sequential dependencies in price history
    - Deep ReLU network head for non-linear regression (Theorem 4.2.1:
      ReLU networks are universal approximators)
    """

    def __init__(
        self,
        input_features: int,
        lstm_hidden: int = 128,
        lstm_layers: int = 2,
        fc_dims: list[int] | None = None,
        dropout: float = 0.2,
        activation: str = "relu",
    ):
        super().__init__()
        if fc_dims is None:
            fc_dims = [128, 64, 32]

        self.lstm = nn.LSTM(
            input_size=input_features,
            hidden_size=lstm_hidden,
            num_layers=lstm_layers,
            batch_first=True,
            dropout=dropout if lstm_layers > 1 else 0.0,
        )

        # Deep feedforward head (Chapter 2 architecture)
        layers = []
        prev_dim = lstm_hidden
        for dim in fc_dims:
            layers.append(nn.Linear(prev_dim, dim))
            layers.append(get_activation(activation))
            layers.append(nn.BatchNorm1d(dim))
            layers.append(nn.Dropout(dropout))
            prev_dim = dim
        layers.append(nn.Linear(prev_dim, 1))
        self.fc = nn.Sequential(*layers)
        self._init_weights()

    def _init_weights(self):
        for name, param in self.lstm.named_parameters():
            if "weight_ih" in name:
                nn.init.xavier_uniform_(param)
            elif "weight_hh" in name:
                nn.init.orthogonal_(param)
            elif "bias" in name:
                nn.init.zeros_(param)
        for m in self.fc.modules():
            if isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)
                nn.init.zeros_(m.bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        lstm_out, _ = self.lstm(x)
        last_hidden = lstm_out[:, -1, :]
        return self.fc(last_hidden).squeeze(-1)


def build_model(
    model_type: str,
    lookback: int,
    n_features: int,
    device: torch.device,
    activation: str = "relu",
) -> nn.Module:
    """
    Factory function to construct a model.

    Args:
        model_type: One of 'feedforward', 'rnn', 'lstm', 'gru', 'cnn', 'hybrid'.
        lookback: Number of past time steps in each input.
        n_features: Number of features per time step.
        device: torch device to place the model on.
        activation: Hidden activation function ('relu', 'sigmoid', 'tanh').

    Returns:
        An nn.Module moved to the specified device.
    """
    if model_type == "feedforward":
        model = FeedforwardNet(input_dim=lookback * n_features, activation=activation)
    elif model_type == "rnn":
        model = RNNNet(input_features=n_features, activation=activation)
    elif model_type == "lstm":
        model = LSTMNet(input_features=n_features, activation=activation)
    elif model_type == "gru":
        model = GRUNet(input_features=n_features, activation=activation)
    elif model_type == "cnn":
        model = CNN1DNet(input_features=n_features, activation=activation)
    elif model_type == "hybrid":
        model = HybridNet(input_features=n_features, activation=activation)
    else:
        raise ValueError(f"Unknown model type: {model_type}")

    return model.to(device)
