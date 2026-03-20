"""
Advanced loss functions for price prediction models.

Extends basic MSE/MAE/Huber with domain-specific losses optimized for:
- Direction prediction (buy/sell signals accuracy)
- Quantile regression (confidence bounds)
- Robust outlier handling (log-cosh)
- Multi-objective optimization (direction + magnitude)
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


class QuantileLoss(nn.Module):
    """
    Quantile loss for predicting confidence bounds.
    
    Useful for trading: predicts not just the expected price,
    but also upper/lower bounds for risk assessment.
    
    Loss = Σ max(q * error, (q - 1) * error)
    where q is the quantile (0.5 = median).
    
    Example:
        q=0.5 → median (MSE-like)
        q=0.9 → upper bound (penalizes underestimation more)
        q=0.1 → lower bound (penalizes overestimation more)
    """
    
    def __init__(self, quantile: float = 0.5):
        super().__init__()
        self.quantile = quantile
    
    def forward(self, predictions: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        error = targets - predictions
        return torch.mean(
            torch.max(self.quantile * error, (self.quantile - 1) * error)
        )


class LogCoshLoss(nn.Module):
    """
    Log-cosh loss: smooth approximation of MAE, reduces impact of large outliers.
    
    Loss ≈ log(cosh(y_pred - y_true))
    
    Advantages:
    - Twice differentiable (better for gradient flow than L1)
    - Less sensitive to large errors than MSE
    - Smooth behavior around zero
    
    Useful for: reducing impact of market anomalies/gaps.
    """
    
    def forward(self, predictions: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        error = predictions - targets
        # log(cosh(x)) ≈ |x| + log(2) for large |x|, but smooth near 0
        return torch.mean(error + F.softplus(-2 * error) - torch.log(torch.tensor(2.0)))


class DirectionWeightedLoss(nn.Module):
    """
    Composite loss balancing direction accuracy and magnitude accuracy.
    
    Total Loss = (1 - α) * direction_loss + α * magnitude_loss
    
    Example: α=0.3 means 70% emphasis on getting direction right (buy/sell),
             30% on magnitude accuracy.
    
    Useful for trading: direction matters more than exact price prediction.
    """
    
    def __init__(self, alpha: float = 0.3):
        """
        Args:
            alpha: Weight for magnitude loss (0.0-1.0).
                   Higher α → prioritize magnitude;
                   Lower α → prioritize direction.
        """
        super().__init__()
        self.alpha = alpha
    
    def forward(self, predictions: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        # Direction component: penalize wrong sign
        direction_error = torch.clamp(
            -torch.sign(targets - torch.tensor(0.0)) * (predictions - targets),
            min=0.0
        )
        direction_loss = torch.mean(direction_error ** 2)
        
        # Magnitude component: standard MAE
        magnitude_loss = torch.mean(torch.abs(predictions - targets))
        
        return (1 - self.alpha) * direction_loss + self.alpha * magnitude_loss


class SymmetricMAPELoss(nn.Module):
    """
    Symmetric Mean Absolute Percentage Error (SMAPE).
    
    Treats over- and under-estimation equally (unlike MAPE).
    Normalized: loss between 0 and 1.
    
    Useful for: percentage-based trading (% return accuracy).
    
    Formula:
        SMAPE = (1/N) Σ 2*|y_pred - y_true| / (|y_pred| + |y_true|)
    """
    
    def forward(self, predictions: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        numerator = 2 * torch.abs(predictions - targets)
        denominator = torch.abs(predictions) + torch.abs(targets)
        
        # Avoid division by zero; if both pred and target are ~0, error is ~0
        result = numerator / (denominator + 1e-8)
        return torch.mean(result)


class PinballLoss(nn.Module):
    """
    Pinball loss (same as quantile loss, but with different interpretation).
    
    Asymmetric loss useful for predicting price movements where
    missing upside vs downside have different costs.
    
    Example: For a long trading signal, missing upside (q=0.9) is worse
             than missing downside (q=0.1).
    """
    
    def __init__(self, quantile: float = 0.5):
        super().__init__()
        self.quantile = quantile
    
    def forward(self, predictions: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        error = targets - predictions
        loss = torch.where(
            error > 0,
            self.quantile * error,
            (1 - self.quantile) * (-error)
        )
        return torch.mean(loss)


class RMSELoss(nn.Module):
    """
    Root Mean Squared Error — interpretable in price units.
    
    Equivalent to MSE but output is in original price scale (dollars, not dollars²).
    
    Useful for: interpretability ("average prediction error: $X").
    """
    
    def forward(self, predictions: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        mse = torch.mean((predictions - targets) ** 2)
        return torch.sqrt(mse + 1e-8)  # Add eps to avoid gradient issues near zero


class HuberLogCombinedLoss(nn.Module):
    """
    Combines Huber loss (robust to outliers) with log-cosh (smooth).
    
    Best of both worlds:
    - Huber: robust to moderate outliers
    - Log-cosh: smooth gradients, extra robustness to extreme outliers
    
    Total Loss = (1 - β) * huber_loss + β * log_cosh_loss
    """
    
    def __init__(self, huber_delta: float = 1.0, beta: float = 0.5):
        super().__init__()
        self.huber = nn.HuberLoss(delta=huber_delta)
        self.logcosh = LogCoshLoss()
        self.beta = beta
    
    def forward(self, predictions: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        huber_l = self.huber(predictions, targets)
        logcosh_l = self.logcosh(predictions, targets)
        return (1 - self.beta) * huber_l + self.beta * logcosh_l


class AdaptiveWeightedLoss(nn.Module):
    """
    Adaptive loss that emphasizes harder-to-predict samples.
    
    Weights = 1 + |error|, so larger errors get higher gradients.
    Helps model focus on difficult predictions in later epochs.
    """
    
    def forward(self, predictions: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        mse = (predictions - targets) ** 2
        weights = 1.0 + torch.abs(predictions - targets)
        return torch.mean(weights * mse)


class ReturnVolatilityLoss(nn.Module):
    """
    Loss that accounts for market regimes (high vs low volatility).
    
    Scales error by inverse volatility estimate:
    - High volatility periods: larger absolute errors acceptable
    - Low volatility periods: expect tight predictions
    
    Useful for: adapting to market conditions.
    """
    
    def __init__(self, volatility_window: int = 20):
        super().__init__()
        self.volatility_window = volatility_window
    
    def forward(self, predictions: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        # Estimate realized volatility from target returns
        returns = targets.diff(dim=0)
        
        # Rolling std dev approximation (simplified)
        volatility = torch.std(returns) + 1e-6
        
        # Inverse volatility weighting (low vol → high weight)
        weights = 1.0 / (volatility + 1e-6)
        
        # Squared error with adaptive weighting
        error = (predictions - targets) ** 2
        weighted_error = weights * error
        
        return torch.mean(weighted_error)


def get_loss_function(loss_name: str, **kwargs) -> nn.Module:
    """
    Factory function to instantiate loss functions by name.
    
    Args:
        loss_name: One of:
            - "mse" → MSELoss
            - "mae" → L1Loss  
            - "huber" → HuberLoss
            - "rmse" → RMSELoss
            - "logcosh" → LogCoshLoss
            - "quantile" → QuantileLoss(quantile=kwargs.get("quantile", 0.5))
            - "pinball" → PinballLoss(quantile=kwargs.get("quantile", 0.5))
            - "smape" → SymmetricMAPELoss
            - "direction_weighted" → DirectionWeightedLoss(alpha=kwargs.get("alpha", 0.3))
            - "huber_logcosh" → HuberLogCombinedLoss(beta=kwargs.get("beta", 0.5))
            - "adaptive_weighted" → AdaptiveWeightedLoss
            - "return_volatility" → ReturnVolatilityLoss
        
        **kwargs: Loss-specific parameters (quantile, alpha, beta, etc.)
    
    Returns:
        Instantiated loss module.
    
    Raises:
        ValueError: If loss_name not recognized.
    """
    loss_name = loss_name.lower()
    
    if loss_name == "mse":
        return nn.MSELoss()
    elif loss_name == "mae":
        return nn.L1Loss()
    elif loss_name == "huber":
        delta = kwargs.get("delta", 1.0)
        return nn.HuberLoss(delta=delta)
    elif loss_name == "rmse":
        return RMSELoss()
    elif loss_name == "logcosh":
        return LogCoshLoss()
    elif loss_name == "quantile":
        quantile = kwargs.get("quantile", 0.5)
        return QuantileLoss(quantile=quantile)
    elif loss_name == "pinball":
        quantile = kwargs.get("quantile", 0.5)
        return PinballLoss(quantile=quantile)
    elif loss_name == "smape":
        return SymmetricMAPELoss()
    elif loss_name == "direction_weighted":
        alpha = kwargs.get("alpha", 0.3)
        return DirectionWeightedLoss(alpha=alpha)
    elif loss_name == "huber_logcosh":
        delta = kwargs.get("delta", 1.0)
        beta = kwargs.get("beta", 0.5)
        return HuberLogCombinedLoss(huber_delta=delta, beta=beta)
    elif loss_name == "adaptive_weighted":
        return AdaptiveWeightedLoss()
    elif loss_name == "return_volatility":
        vol_window = kwargs.get("volatility_window", 20)
        return ReturnVolatilityLoss(volatility_window=vol_window)
    else:
        raise ValueError(
            f"Unknown loss function: {loss_name}. Supported: "
            "mse, mae, huber, rmse, logcosh, quantile, pinball, smape, "
            "direction_weighted, huber_logcosh, adaptive_weighted, return_volatility"
        )
