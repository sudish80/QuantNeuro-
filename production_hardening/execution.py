"""Hardened Binance execution with signature, retries, idempotency, and order lifecycle utilities."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

import requests

from production_hardening.config import BinanceConfig
from production_hardening.security import hmac_sha256_hex


@dataclass
class ExecutionResult:
    status: str
    order_id: str | None
    symbol: str
    side: str
    quantity: float
    raw: dict[str, Any]


@dataclass
class FillReconciliation:
    order_id: str
    symbol: str
    status: str
    executed_qty: float
    cumulative_quote_qty: float
    avg_fill_price: float
    fee_total: float
    fee_by_asset: dict[str, float]


class BinanceExecutor:
    def __init__(self, cfg: BinanceConfig, mode: str = "paper"):
        self.cfg = cfg
        self.mode = mode
        self.session = requests.Session()

    def _signed_params(self, params: dict[str, Any]) -> dict[str, Any]:
        data = dict(params)
        data["timestamp"] = int(time.time() * 1000)
        data["recvWindow"] = self.cfg.recv_window_ms
        query = "&".join(f"{k}={data[k]}" for k in sorted(data.keys()))
        data["signature"] = hmac_sha256_hex(self.cfg.api_secret, query)
        return data

    def _request_with_retry(self, method: str, path: str, params: dict[str, Any], retries: int = 3) -> dict[str, Any]:
        url = f"{self.cfg.base_url}{path}"
        headers = {
            "X-MBX-APIKEY": self.cfg.api_key,
            "X-Idempotency-Key": params.get("newClientOrderId", str(uuid.uuid4())),
        }
        last_err: Exception | None = None

        for attempt in range(1, retries + 1):
            try:
                if method == "POST":
                    resp = self.session.post(url, headers=headers, data=self._signed_params(params), timeout=15)
                elif method == "DELETE":
                    resp = self.session.delete(url, headers=headers, params=self._signed_params(params), timeout=15)
                else:
                    resp = self.session.get(url, headers=headers, params=self._signed_params(params), timeout=15)
                resp.raise_for_status()
                return resp.json() if resp.text else {}
            except Exception as ex:
                last_err = ex
                if attempt < retries:
                    time.sleep(0.5 * attempt)
        raise RuntimeError(f"Execution request failed after retries: {last_err}")

    def place_market_order(self, symbol: str, side: str, quantity: float) -> ExecutionResult:
        if self.mode == "paper":
            return ExecutionResult(
                status="FILLED",
                order_id=f"paper-{uuid.uuid4().hex[:12]}",
                symbol=symbol,
                side=side,
                quantity=quantity,
                raw={"mode": "paper", "fills": [{"qty": quantity}]},
            )

        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": quantity,
            "newClientOrderId": uuid.uuid4().hex,
        }
        data = self._request_with_retry("POST", "/api/v3/order", params)
        return ExecutionResult(
            status=data.get("status", "UNKNOWN"),
            order_id=str(data.get("orderId")) if data.get("orderId") is not None else None,
            symbol=symbol,
            side=side,
            quantity=float(quantity),
            raw=data,
        )

    def get_order(self, symbol: str, order_id: str) -> dict[str, Any]:
        if self.mode == "paper":
            return {"status": "FILLED", "orderId": order_id, "symbol": symbol}
        return self._request_with_retry("GET", "/api/v3/order", {"symbol": symbol, "orderId": order_id})

    def cancel_order(self, symbol: str, order_id: str) -> dict[str, Any]:
        if self.mode == "paper":
            return {"status": "CANCELED", "orderId": order_id, "symbol": symbol}
        return self._request_with_retry("DELETE", "/api/v3/order", {"symbol": symbol, "orderId": order_id})

    def wait_for_fill(self, symbol: str, order_id: str, timeout_sec: int = 20) -> dict[str, Any]:
        start = time.time()
        last = {}
        while time.time() - start < timeout_sec:
            last = self.get_order(symbol, order_id)
            status = last.get("status", "UNKNOWN")
            if status in {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}:
                return last
            time.sleep(1)
        return last

    def cancel_replace(self, symbol: str, old_order_id: str, side: str, quantity: float) -> dict[str, Any]:
        canceled = self.cancel_order(symbol, old_order_id)
        new_order = self.place_market_order(symbol=symbol, side=side, quantity=quantity)
        return {
            "canceled": canceled,
            "replacement": {
                "status": new_order.status,
                "orderId": new_order.order_id,
                "symbol": new_order.symbol,
                "side": new_order.side,
                "quantity": new_order.quantity,
            },
        }

    def get_order_trades(self, symbol: str, order_id: str) -> list[dict[str, Any]]:
        if self.mode == "paper":
            return [{"qty": "0", "price": "0", "commission": "0", "commissionAsset": "USDT"}]
        params = {"symbol": symbol, "orderId": order_id, "limit": 1000}
        data = self._request_with_retry("GET", "/api/v3/myTrades", params)
        return data if isinstance(data, list) else []

    def reconcile_order(self, symbol: str, order_id: str) -> FillReconciliation:
        order = self.get_order(symbol, order_id)
        status = str(order.get("status", "UNKNOWN"))

        if self.mode == "paper":
            executed_qty = float(order.get("executedQty", 0.0) or 0.0)
            cumulative_quote_qty = float(order.get("cummulativeQuoteQty", 0.0) or 0.0)
            avg_fill_price = (cumulative_quote_qty / executed_qty) if executed_qty > 0 else 0.0
            return FillReconciliation(
                order_id=str(order_id),
                symbol=symbol,
                status=status,
                executed_qty=executed_qty,
                cumulative_quote_qty=cumulative_quote_qty,
                avg_fill_price=avg_fill_price,
                fee_total=0.0,
                fee_by_asset={"USDT": 0.0},
            )

        trades = self.get_order_trades(symbol, order_id)
        fee_by_asset: dict[str, float] = {}
        total_qty = 0.0
        total_quote = 0.0

        for t in trades:
            qty = float(t.get("qty", 0.0) or 0.0)
            price = float(t.get("price", 0.0) or 0.0)
            commission = float(t.get("commission", 0.0) or 0.0)
            commission_asset = str(t.get("commissionAsset", ""))

            total_qty += qty
            total_quote += qty * price
            fee_by_asset[commission_asset] = fee_by_asset.get(commission_asset, 0.0) + commission

        fee_total = float(sum(fee_by_asset.values()))
        avg_fill_price = (total_quote / total_qty) if total_qty > 0 else 0.0
        return FillReconciliation(
            order_id=str(order_id),
            symbol=symbol,
            status=status,
            executed_qty=total_qty,
            cumulative_quote_qty=total_quote,
            avg_fill_price=avg_fill_price,
            fee_total=fee_total,
            fee_by_asset=fee_by_asset,
        )
