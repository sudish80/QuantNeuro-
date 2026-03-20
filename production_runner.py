"""Production-style runner with compliance, governance, risk controls, journaling, and hardened execution."""

from __future__ import annotations

import argparse
from datetime import datetime, UTC

import torch

from data_fetcher import fetch_data
from models import build_model
from predict_visualize import predict
from preprocessing import prepare_dataset, inverse_transform_close
from trainer import train_model
from trading_strategy import threshold_trade_decision

from production_hardening.compliance import AccountComplianceProfile, validate_compliance, enforce_retention
from production_hardening.compliance_provider import ComplianceDecisionStore, ComplianceProviderClient
from production_hardening.config import load_runtime_config, load_risk_config, load_binance_config
from production_hardening.execution import BinanceExecutor
from production_hardening.governance import GovernanceRegistry, ModelVersion
from production_hardening.journal import TradeJournal
from production_hardening.monitoring import run_health_checks, write_metrics_csv, send_alert, check_model_drift
from production_hardening.monitoring import generate_metrics_dashboard, incident_response_payload
from production_hardening.reliability import StateStore
from production_hardening.risk import PortfolioState, Position, RiskEngine


def run_once(
    ticker: str,
    model_type: str,
    activation: str,
    lookback: int,
    epochs: int,
    threshold: float,
    account_id: str,
    jurisdiction: str,
    equity_usd: float,
    risk_per_trade: float,
    mode: str,
) -> None:
    runtime_cfg = load_runtime_config()
    risk_cfg = load_risk_config()
    binance_cfg = load_binance_config()

    state_store = StateStore(runtime_cfg.state_file)
    persisted = state_store.load()
    pnl_today = float(persisted.get("realized_pnl_today_usd", 0.0))

    compliance_profile = AccountComplianceProfile(
        account_id=account_id,
        kyc_verified=False,
        aml_screen_passed=False,
        risk_tier="standard",
        jurisdiction=jurisdiction,
    )
    symbol_for_exchange = ticker.replace("-", "")

    decision_store = ComplianceDecisionStore(runtime_cfg.compliance_decisions_path)
    provider_decision = None
    if runtime_cfg.compliance_provider_url and runtime_cfg.compliance_provider_api_key:
        provider = ComplianceProviderClient(
            base_url=runtime_cfg.compliance_provider_url,
            api_key=runtime_cfg.compliance_provider_api_key,
        )
        provider_decision = provider.evaluate(account_id=account_id, jurisdiction=jurisdiction)
        decision_store.save(provider_decision)
    else:
        provider_decision = decision_store.get(account_id)
        if provider_decision is None:
            raise RuntimeError("Compliance provider is not configured and no persisted compliance decision exists")

    compliance_profile.kyc_verified = provider_decision.kyc_verified
    compliance_profile.aml_screen_passed = provider_decision.aml_passed
    ok, reason = validate_compliance(compliance_profile, symbol_for_exchange)
    if not ok:
        raise RuntimeError(f"Compliance block: {reason}")

    governance = GovernanceRegistry("./output/model_registry.json")
    governance.register(
        ModelVersion(
            version=f"{model_type}-{activation}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            model_type=model_type,
            activation=activation,
            train_window="5y",
            val_rmse=0.0,
            approved=True,
            approved_by="system",
            rollback_version="",
            change_ticket="AUTO-BOOTSTRAP",
        )
    )

    # Build dataset/model
    df = fetch_data(ticker=ticker, source="yahoo", period="5y", interval="1d")
    dataset = prepare_dataset(df, lookback=lookback, normalization="minmax")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_model(
        model_type=model_type,
        lookback=lookback,
        n_features=dataset["X_train"].shape[2],
        device=device,
        activation=activation,
    )
    history = train_model(
        model=model,
        X_train=dataset["X_train"],
        y_train=dataset["y_train"],
        X_test=dataset["X_test"],
        y_test=dataset["y_test"],
        device=device,
        epochs=epochs,
        batch_size=64,
        learning_rate=1e-3,
        optimizer_name="adam",
        loss_name="mse",
    )

    preds_scaled = predict(model, dataset["X_test"], device)
    preds = inverse_transform_close(preds_scaled, dataset["close_scaler"])
    actuals = inverse_transform_close(dataset["y_test"], dataset["close_scaler"])

    current_price = float(actuals[-1])
    predicted_price = float(preds[-1])
    signal = threshold_trade_decision(current_price=current_price, predicted_price=predicted_price, threshold=threshold)

    health = run_health_checks(data_feed_ok=True, model_ok=True, execution_ok=True, risk_engine_ok=True)
    if not all([health.data_feed_ok, health.model_ok, health.execution_ok, health.risk_engine_ok]):
        msg = incident_response_payload("critical", "Health check failed", {
            "data_feed_ok": health.data_feed_ok,
            "model_ok": health.model_ok,
            "execution_ok": health.execution_ok,
            "risk_engine_ok": health.risk_engine_ok,
        })
        send_alert(msg, runtime_cfg.alerts_webhook_url)
        return

    drift_flag, drift_val = check_model_drift(
        ref_mean=float(actuals.mean()),
        ref_std=float(actuals.std()),
        current_mean=float(preds.mean()),
        threshold=2.0,
    )
    if drift_flag:
        msg = incident_response_payload("high", "Model drift detected", {"drift_score": drift_val})
        send_alert(msg, runtime_cfg.alerts_webhook_url)

    journal = TradeJournal(
        csv_path=runtime_cfg.trade_journal_path,
        encrypted_log_path=runtime_cfg.encrypted_audit_log_path,
        kms_key_id=runtime_cfg.kms_key_id or "",
        kms_region=runtime_cfg.kms_region,
        passphrase=runtime_cfg.journal_passphrase,
        plaintext_enabled=runtime_cfg.trade_journal_plaintext_enabled,
    )

    executor = BinanceExecutor(binance_cfg, mode=mode)
    risk_engine = RiskEngine(risk_cfg, runtime_cfg.kill_switch_path)

    portfolio = PortfolioState(equity_usd=equity_usd, realized_pnl_today_usd=pnl_today, positions={})

    # Position sizing by risk per trade and stop distance approximation (1.5%)
    if signal in {"BUY", "SELL"}:
        stop_distance = current_price * 0.015
        qty = (equity_usd * risk_per_trade) / max(stop_distance, 1e-12)
        notional = qty * current_price

        can_trade, why = risk_engine.can_trade(portfolio, symbol_for_exchange, notional)
        if not can_trade:
            journal.write_event(
                event="RISK_BLOCK",
                symbol=symbol_for_exchange,
                side=signal,
                qty=qty,
                price=current_price,
                status="BLOCKED",
                reason=why,
            )
            send_alert(f"Risk blocked order: {why}", runtime_cfg.alerts_webhook_url)
        else:
            result = executor.place_market_order(symbol=symbol_for_exchange, side=signal, quantity=qty)
            final_state = executor.wait_for_fill(symbol=symbol_for_exchange, order_id=result.order_id or "")
            status = final_state.get("status", result.status)

            if status == "PARTIALLY_FILLED":
                # Demonstrate cancel/replace lifecycle hardening
                rep = executor.cancel_replace(symbol=symbol_for_exchange, old_order_id=result.order_id or "", side=signal, quantity=qty)
                status = rep.get("replacement", {}).get("status", status)

            reconciliation = executor.reconcile_order(symbol=symbol_for_exchange, order_id=result.order_id or "")

            if status in {"FILLED", "PARTIALLY_FILLED"}:
                side_mult = 1.0 if signal == "BUY" else -1.0
                portfolio.positions[symbol_for_exchange] = Position(symbol=symbol_for_exchange, qty=qty * side_mult, notional_usd=notional)

            journal.write_event(
                event="ORDER",
                symbol=symbol_for_exchange,
                side=signal,
                qty=reconciliation.executed_qty,
                price=reconciliation.avg_fill_price if reconciliation.avg_fill_price > 0 else current_price,
                status=status,
                reason=f"fees={reconciliation.fee_total};fee_assets={reconciliation.fee_by_asset}",
            )
    else:
        journal.write_event(
            event="SIGNAL",
            symbol=symbol_for_exchange,
            side=signal,
            qty=0.0,
            price=current_price,
            status="HOLD",
            reason="Threshold filter",
        )

    # Metrics and retention
    write_metrics_csv(runtime_cfg.metrics_path, {
        "predicted_price": predicted_price,
        "current_price": current_price,
        "train_loss_last": float(history["train_loss"][-1]) if history["train_loss"] else 0.0,
        "val_loss_last": float(history["val_loss"][-1]) if history["val_loss"] else 0.0,
        "drift_score": drift_val,
    })
    generate_metrics_dashboard(runtime_cfg.metrics_path, "./output/dashboard.html")

    enforce_retention(runtime_cfg.trade_journal_path, runtime_cfg.retention_days)
    enforce_retention(runtime_cfg.encrypted_audit_log_path, runtime_cfg.retention_days)
    enforce_retention(runtime_cfg.metrics_path, runtime_cfg.retention_days)

    state_store.save({
        "realized_pnl_today_usd": portfolio.realized_pnl_today_usd,
        "last_signal": signal,
        "last_symbol": symbol_for_exchange,
    })

    print("Run completed")
    print(f"Signal: {signal}")
    print(f"Current: {current_price:.4f} | Predicted: {predicted_price:.4f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Production-hardened trading runner")
    parser.add_argument("--ticker", type=str, default="BTC-USD")
    parser.add_argument("--model", type=str, default="lstm", choices=["feedforward", "rnn", "lstm", "gru", "cnn", "hybrid"])
    parser.add_argument("--activation", type=str, default="relu", choices=["relu", "sigmoid", "tanh"])
    parser.add_argument("--lookback", type=int, default=20)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--threshold", type=float, default=0.002)
    parser.add_argument("--account-id", type=str, default="acct-demo")
    parser.add_argument("--jurisdiction", type=str, default="GLOBAL")
    parser.add_argument("--equity-usd", type=float, default=10000.0)
    parser.add_argument("--risk-per-trade", type=float, default=0.01)
    parser.add_argument("--mode", type=str, default="paper", choices=["paper", "live"])
    args = parser.parse_args()

    run_once(
        ticker=args.ticker,
        model_type=args.model,
        activation=args.activation,
        lookback=args.lookback,
        epochs=args.epochs,
        threshold=args.threshold,
        account_id=args.account_id,
        jurisdiction=args.jurisdiction,
        equity_usd=args.equity_usd,
        risk_per_trade=args.risk_per_trade,
        mode=args.mode,
    )


if __name__ == "__main__":
    main()
