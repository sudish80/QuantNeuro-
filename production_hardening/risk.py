"""Risk guardrails: exposure limits, daily loss limits, circuit breaker, and kill switch."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

from production_hardening.config import RiskConfig


@dataclass
class Position:
    symbol: str
    qty: float
    notional_usd: float


@dataclass
class PortfolioState:
    equity_usd: float
    realized_pnl_today_usd: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    breaker_until: datetime | None = None


class RiskEngine:
    def __init__(self, cfg: RiskConfig, kill_switch_path: str):
        self.cfg = cfg
        self.kill_switch_path = Path(kill_switch_path)

    def kill_switch_active(self) -> bool:
        return self.kill_switch_path.exists()

    def trip_kill_switch(self, reason: str) -> None:
        self.kill_switch_path.write_text(reason, encoding="utf-8")

    def clear_kill_switch(self) -> None:
        self.kill_switch_path.unlink(missing_ok=True)

    def _daily_loss_pct(self, state: PortfolioState) -> float:
        if state.equity_usd <= 0:
            return 1.0
        return max(0.0, -state.realized_pnl_today_usd / state.equity_usd)

    def _total_exposure_pct(self, state: PortfolioState) -> float:
        if state.equity_usd <= 0:
            return 1.0
        total = sum(abs(p.notional_usd) for p in state.positions.values())
        return total / state.equity_usd

    def _asset_exposure_pct(self, state: PortfolioState, symbol: str) -> float:
        if state.equity_usd <= 0:
            return 1.0
        pos = state.positions.get(symbol)
        notional = abs(pos.notional_usd) if pos else 0.0
        return notional / state.equity_usd

    def can_trade(self, state: PortfolioState, symbol: str, new_notional_usd: float) -> tuple[bool, str]:
        now = datetime.now(timezone.utc)

        if self.kill_switch_active():
            return False, "Kill switch active"

        if state.breaker_until and now < state.breaker_until:
            return False, f"Circuit breaker active until {state.breaker_until.isoformat()}"

        daily_loss = self._daily_loss_pct(state)
        if daily_loss >= self.cfg.max_daily_loss_pct:
            return False, f"Daily loss limit exceeded: {daily_loss:.2%}"

        # Evaluate post-trade exposure
        current_total = sum(abs(p.notional_usd) for p in state.positions.values())
        new_total = current_total + abs(new_notional_usd)
        total_exposure_pct = new_total / max(state.equity_usd, 1e-12)
        if total_exposure_pct > self.cfg.max_total_exposure_pct:
            return False, f"Total exposure limit exceeded: {total_exposure_pct:.2%}"

        asset_exposure_pct = (self._asset_exposure_pct(state, symbol) + abs(new_notional_usd) / max(state.equity_usd, 1e-12))
        if asset_exposure_pct > self.cfg.max_asset_exposure_pct:
            return False, f"Asset exposure limit exceeded for {symbol}: {asset_exposure_pct:.2%}"

        if daily_loss >= self.cfg.circuit_breaker_loss_pct:
            state.breaker_until = now + timedelta(seconds=self.cfg.circuit_breaker_cooldown_sec)
            return False, "Circuit breaker triggered"

        return True, "OK"
