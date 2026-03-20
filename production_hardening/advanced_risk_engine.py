"""
Enhanced risk engine with advanced metrics and kill-switch rules.

Provides:
- Value-at-Risk (VaR) and Conditional Value-at-Risk (CVaR) calculations
- Stress testing scenarios
- Kill-switch rules for circuit breaker protection
- Cross-asset exposure limits
- Pre-trade and post-trade risk checks
"""

import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime
import json


# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class Position:
    """Represents a trading position."""

    ticker: str
    quantity: float
    entry_price: float
    current_price: float
    side: str  # 'LONG' or 'SHORT'

    @property
    def notional_value(self) -> float:
        return abs(self.quantity * self.current_price)

    @property
    def pnl(self) -> float:
        if self.side == "LONG":
            return self.quantity * (self.current_price - self.entry_price)
        else:
            return self.quantity * (self.entry_price - self.current_price)

    @property
    def pnl_pct(self) -> float:
        if self.entry_price == 0:
            return 0.0
        return (self.pnl / (self.quantity * self.entry_price)) * 100


@dataclass
class RiskMetrics:
    """Risk metrics snapshot."""

    var_95: float  # 95% VaR
    cvar_95: float  # 95% CVaR (ES)
    max_drawdown: float
    leverage: float
    total_exposure: float
    margin_utilization: float
    concentrated_sector: str
    concentration_pct: float
    is_stressed: bool
    stress_scenario: Optional[str] = None


# ============================================================================
# ADVANCED RISK CALCULATIONS
# ============================================================================


class AdvancedRiskEngine:
    """Enhanced risk engine with VaR, CVaR, stress testing, and kill-switch logic."""

    def __init__(
        self,
        account_equity: float = 100000.0,
        max_leverage: float = 3.0,
        max_drawdown_pct: float = 0.20,
        max_margin_util: float = 0.90,
        max_sector_concentration: float = 0.50,
        var_confidence: float = 0.95,
    ):
        self.account_equity = account_equity
        self.max_leverage = max_leverage
        self.max_drawdown_pct = max_drawdown_pct
        self.max_margin_util = max_margin_util
        self.max_sector_concentration = max_sector_concentration
        self.var_confidence = var_confidence

        self.positions: Dict[str, Position] = {}
        self.pnl_history: List[float] = []
        self.sector_map: Dict[str, str] = {}  # ticker -> sector
        self.stress_active = False
        self.kill_switch_active = False

    def add_position(self, position: Position):
        """Add a trade position."""
        self.positions[position.ticker] = position

    def close_position(self, ticker: str):
        """Close a position."""
        if ticker in self.positions:
            del self.positions[ticker]

    def update_position_price(self, ticker: str, new_price: float):
        """Update current price for a position."""
        if ticker in self.positions:
            self.positions[ticker].current_price = new_price

    # ========================================================================
    # VaR & CVaR CALCULATIONS
    # ========================================================================

    def calculate_var_parametric(
        self, confidence_level: float = 0.95, returns_std: float = 0.02
    ) -> float:
        """
        Calculate parametric VaR using normal distribution.
        VaR = -mu + sigma * z_confidence
        """
        if not self.positions:
            return 0.0

        total_notional = sum(p.notional_value for p in self.positions.values())
        z_score = {0.90: 1.28, 0.95: 1.645, 0.99: 2.326}.get(
            confidence_level, 1.645
        )

        # VaR = portfolio_value * std_dev * z_score
        var = total_notional * returns_std * z_score
        return var

    def calculate_var_historical(
        self, returns: np.ndarray, confidence_level: float = 0.95
    ) -> float:
        """Calculate historical VaR from return distribution."""
        percentile = (1 - confidence_level) * 100
        var = np.percentile(returns, percentile)
        return abs(var)

    def calculate_cvar(
        self, returns: np.ndarray, confidence_level: float = 0.95
    ) -> float:
        """
        Calculate Conditional VaR (Expected Shortfall).
        CVaR = average of returns worse than VaR.
        """
        percentile = (1 - confidence_level) * 100
        var = np.percentile(returns, percentile)
        worse_returns = returns[returns <= var]

        if len(worse_returns) == 0:
            return abs(var)

        cvar = np.mean(worse_returns)
        return abs(cvar)

    # ========================================================================
    # STRESS TESTING
    # ========================================================================

    def stress_test_scenario(self, scenario_name: str) -> Dict[str, float]:
        """
        Apply stress scenario to current portfolio.
        
        Scenarios:
        - market_crash: -20% price move
        - volatility_shock: -15% with 3x volatility
        - sector_rotation: winners -15%, losers -5%
        - liquidity_crisis: wider bid-ask spreads (2% slippage)
        """
        stressed_pnls = {}

        for ticker, position in self.positions.items():
            base_pnl = position.pnl

            if scenario_name == "market_crash":
                stressed_price = position.current_price * 0.80
                stressed_pnl = base_pnl * 0.80

            elif scenario_name == "volatility_shock":
                stressed_price = position.current_price * 0.85
                stressed_pnl = base_pnl * 0.85

            elif scenario_name == "sector_rotation":
                # Assume tech down 15%, financials down 5%
                sector = self.sector_map.get(ticker, "other")
                if sector == "technology":
                    stressed_pnl = base_pnl * 0.85
                elif sector == "financials":
                    stressed_pnl = base_pnl * 0.95
                else:
                    stressed_pnl = base_pnl * 0.90

            elif scenario_name == "liquidity_crisis":
                # Apply 2% slippage cost
                slippage = position.notional_value * 0.02
                stressed_pnl = base_pnl - slippage

            else:
                stressed_pnl = base_pnl

            stressed_pnls[ticker] = stressed_pnl

        return stressed_pnls

    def get_worst_case_scenario(self) -> Tuple[str, float]:
        """Find scenario with worst P&L."""
        scenarios = [
            "market_crash",
            "volatility_shock",
            "sector_rotation",
            "liquidity_crisis",
        ]
        worst_scenario = None
        worst_pnl = float("inf")

        for scenario in scenarios:
            stressed_pnls = self.stress_test_scenario(scenario)
            total_stressed_pnl = sum(stressed_pnls.values())

            if total_stressed_pnl < worst_pnl:
                worst_pnl = total_stressed_pnl
                worst_scenario = scenario

        return worst_scenario or "unknown", worst_pnl

    # ========================================================================
    # EXPOSURE & LEVERAGE CALCULATIONS
    # ========================================================================

    def calculate_total_exposure(self) -> float:
        """Calculate total notional exposure in USD."""
        return sum(p.notional_value for p in self.positions.values())

    def calculate_leverage_ratio(self) -> float:
        """Calculate leverage = total_exposure / account_equity."""
        total_expo = self.calculate_total_exposure()
        return total_expo / self.account_equity if self.account_equity > 0 else 0.0

    def calculate_margin_utilization(self) -> float:
        """
        Calculate margin utilization.
        Assumes 25% initial margin requirement.
        """
        total_expo = self.calculate_total_exposure()
        margin_required = total_expo * 0.25
        return margin_required / self.account_equity if self.account_equity > 0 else 0.0

    def get_sector_concentration(self) -> Tuple[str, float]:
        """
        Get most concentrated sector and its percentage.
        Example: ('technology', 0.45) -> tech is 45% of portfolio.
        """
        sector_notional = {}

        for ticker, position in self.positions.items():
            sector = self.sector_map.get(ticker, "other")
            sector_notional[sector] = sector_notional.get(sector, 0) + position.notional_value

        total_expo = sum(sector_notional.values())
        if total_expo == 0:
            return "none", 0.0

        max_sector = max(sector_notional, key=sector_notional.get)
        max_pct = sector_notional[max_sector] / total_expo

        return max_sector, max_pct

    # ========================================================================
    # DRAWDOWN TRACKING
    # ========================================================================

    def calculate_max_drawdown(self, equity_curve: List[float]) -> float:
        """Calculate maximum drawdown from equity curve."""
        if len(equity_curve) < 2:
            return 0.0

        cumulative_returns = np.array(equity_curve)
        running_max = np.maximum.accumulate(cumulative_returns)
        drawdown = (cumulative_returns - running_max) / running_max

        return float(np.min(drawdown))

    def record_equity_update(self, current_equity: float):
        """Record equity for drawdown tracking."""
        self.pnl_history.append(current_equity)

    # ========================================================================
    # KILL-SWITCH LOGIC
    # ========================================================================

    def check_kill_switch_conditions(self) -> Tuple[bool, List[str]]:
        """
        Check if any kill-switch conditions are triggered.
        Returns (should_activate, triggered_conditions).
        """
        triggered = []

        # Leverage limit breach
        leverage = self.calculate_leverage_ratio()
        if leverage > self.max_leverage:
            triggered.append(
                f"EXCESSIVE_LEVERAGE: {leverage:.2f}x > {self.max_leverage}x"
            )

        # Margin utilization
        margin_util = self.calculate_margin_utilization()
        if margin_util > self.max_margin_util:
            triggered.append(
                f"MARGIN_OVERUTILIZED: {margin_util:.1%} > {self.max_margin_util:.1%}"
            )

        # Sector concentration
        sector, concentration = self.get_sector_concentration()
        if concentration > self.max_sector_concentration:
            triggered.append(
                f"SECTOR_CONCENTRATED: {sector} {concentration:.1%} > {self.max_sector_concentration:.1%}"
            )

        # Stress test failure
        worst_scenario, worst_pnl = self.get_worst_case_scenario()
        current_equity = self.account_equity + sum(p.pnl for p in self.positions.values())
        equity_after_stress = current_equity + worst_pnl

        if equity_after_stress < self.account_equity * 0.80:  # 20% loss threshold
            triggered.append(
                f"STRESS_TEST_FAILURE: {worst_scenario} -> {equity_after_stress:.0f} (target: {self.account_equity * 0.80:.0f})"
            )

        should_activate = len(triggered) > 0
        return should_activate, triggered

    def activate_kill_switch(self) -> Dict[str, any]:
        """Activate kill-switch: liquidate all positions and go to cash."""
        liquidation_plan = {}

        for ticker, position in self.positions.items():
            liquidation_plan[ticker] = {
                "action": "LIQUIDATE",
                "quantity": position.quantity,
                "current_price": position.current_price,
                "notional": position.notional_value,
            }

        self.kill_switch_active = True
        return liquidation_plan

    # ========================================================================
    # PRE-TRADE RISK CHECKS
    # ========================================================================

    def pre_trade_risk_check(
        self, ticker: str, quantity: float, side: str, entry_price: float
    ) -> Tuple[bool, List[str]]:
        """
        Check if proposed trade violates risk limits.
        Returns (is_allowed, violations).
        """
        violations = []

        # Create hypothetical position
        hyp_position = Position(
            ticker=ticker,
            quantity=quantity,
            entry_price=entry_price,
            current_price=entry_price,
            side=side,
        )

        # Simulate adding this position
        self.positions[ticker] = hyp_position

        # Check leverage
        new_leverage = self.calculate_leverage_ratio()
        if new_leverage > self.max_leverage:
            violations.append(
                f"Trade would exceed leverage limit: {new_leverage:.2f}x > {self.max_leverage}x"
            )

        # Check margin utilization
        new_margin = self.calculate_margin_utilization()
        if new_margin > self.max_margin_util:
            violations.append(
                f"Trade would overutilize margin: {new_margin:.1%} > {self.max_margin_util:.1%}"
            )

        # Check sector concentration
        sector, concentration = self.get_sector_concentration()
        if concentration > self.max_sector_concentration:
            violations.append(
                f"Trade would exceed sector concentration: {sector} {concentration:.1%}"
            )

        # Remove hypothetical position
        del self.positions[ticker]

        return len(violations) == 0, violations

    # ========================================================================
    # POST-TRADE RISK CHECKS
    # ========================================================================

    def post_trade_risk_check(self) -> Tuple[bool, List[str]]:
        """Validate current portfolio meets all risk criteria."""
        violations = []

        should_activate_ks, ks_triggers = self.check_kill_switch_conditions()
        if should_activate_ks:
            violations.extend(ks_triggers)

        return len(violations) == 0, violations

    # ========================================================================
    # RISK METRICS SNAPSHOT
    # ========================================================================

    def get_risk_metrics(
        self, returns: Optional[np.ndarray] = None
    ) -> RiskMetrics:
        """Get comprehensive risk metrics snapshot."""
        if returns is None or len(returns) < 10:
            # Use parametric if not enough historical data
            var_95 = self.calculate_var_parametric(0.95, 0.02)
            cvar_95 = var_95 * 1.2  # Approximation
        else:
            var_95 = self.calculate_var_historical(returns, 0.95)
            cvar_95 = self.calculate_cvar(returns, 0.95)

        max_dd = (
            self.calculate_max_drawdown(self.pnl_history)
            if len(self.pnl_history) > 1
            else 0.0
        )
        leverage = self.calculate_leverage_ratio()
        total_expo = self.calculate_total_exposure()
        margin_util = self.calculate_margin_utilization()
        sector, concentration = self.get_sector_concentration()

        should_stress, triggers = self.check_kill_switch_conditions()

        return RiskMetrics(
            var_95=var_95,
            cvar_95=cvar_95,
            max_drawdown=max_dd,
            leverage=leverage,
            total_exposure=total_expo,
            margin_utilization=margin_util,
            concentrated_sector=sector,
            concentration_pct=concentration,
            is_stressed=should_stress,
            stress_scenario=triggers[0] if triggers else None,
        )

    # ========================================================================
    # REPORTING
    # ========================================================================

    def generate_risk_report(self) -> str:
        """Generate human-readable risk report."""
        metrics = self.get_risk_metrics()

        report = f"""
╔════════════════════════════════════════════════════════════════╗
║                     RISK METRICS REPORT                        ║
║                  {datetime.utcnow().isoformat()}           ║
╠════════════════════════════════════════════════════════════════╣
║ PORTFOLIO EXPOSURE
║   Total Notional:        ${metrics.total_exposure:,.0f}
║   Account Equity:        ${self.account_equity:,.0f}
║   Leverage Ratio:        {metrics.leverage:.2f}x / {self.max_leverage}x max
║   Margin Utilization:    {metrics.margin_utilization:.1%} / {self.max_margin_util:.1%} max
║
║ RISK METRICS
║   VaR (95%):             ${metrics.var_95:,.0f}
║   CVaR (95%):            ${metrics.cvar_95:,.0f}
║   Max Drawdown:          {metrics.max_drawdown:.2%}
║
║ CONCENTRATION RISK
║   Top Sector:            {metrics.concentrated_sector} ({metrics.concentration_pct:.1%})
║   Concentration Limit:   {self.max_sector_concentration:.1%}
║
║ STRESS STATUS
║   Stressed:              {'YES ⚠️' if metrics.is_stressed else 'NO ✓'}
║   Scenario:              {metrics.stress_scenario or 'None'}
║
║ KILL-SWITCH
║   Active:                {'YES - LIQUIDATING 🔴' if self.kill_switch_active else 'NO - NORMAL 🟢'}
╚════════════════════════════════════════════════════════════════╝
"""
        return report
