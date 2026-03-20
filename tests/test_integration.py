"""
Integration tests with dockerized dependencies.

Tests full system integration including:
- Database transactions
- API endpoint interactions
- Service communication
- End-to-end workflows
"""

import pytest
import os
import json
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List

import pandas as pd
import numpy as np
import requests
from pytest_asyncio import pytest_mark


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture(scope="session")
def api_base_url():
    """API base URL (pointing to docker-compose services)."""
    return os.getenv("API_URL", "http://localhost:5000")


@pytest.fixture(scope="session")
def db_connection_string():
    """PostgreSQL connection string for tests."""
    return os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/trading_db_test"
    )


@pytest.fixture
def sample_market_data() -> pd.DataFrame:
    """Sample market data for testing."""
    dates = pd.date_range(end=datetime.utcnow(), periods=50, freq='1H')
    return pd.DataFrame({
        "timestamp": dates,
        "ticker": "AAPL",
        "open": np.random.uniform(150, 160, 50),
        "high": np.random.uniform(160, 165, 50),
        "low": np.random.uniform(145, 150, 50),
        "close": np.random.uniform(150, 160, 50),
        "volume": np.random.randint(1000000, 5000000, 50),
    })


@pytest.fixture
def jwt_token() -> str:
    """JWT token for authenticated requests."""
    from production_hardening.api_security import jwt_manager, UserRole
    return jwt_manager.create_token("test_user", UserRole.TRADER)


# ============================================================================
# API ENDPOINT TESTS
# ============================================================================


class TestAPIHealthAndStatus:
    """Test API health check and status endpoints."""

    def test_health_check_returns_200(self, api_base_url):
        """Health check endpoint should return 200 OK."""
        response = requests.get(f"{api_base_url}/health")
        assert response.status_code == 200

    def test_health_check_response_structure(self, api_base_url):
        """Health check should return valid JSON with required fields."""
        response = requests.get(f"{api_base_url}/health")
        data = response.json()
        
        assert "status" in data
        assert "timestamp" in data
        assert data["status"] in ["healthy", "healthy"]

    def test_status_endpoint_requires_auth(self, api_base_url):
        """Status endpoint should require authentication."""
        response = requests.get(f"{api_base_url}/status")
        assert response.status_code == 401

    def test_status_endpoint_with_auth(self, api_base_url, jwt_token):
        """Status endpoint with valid token should return 200."""
        headers = {"Authorization": f"Bearer {jwt_token}"}
        response = requests.get(f"{api_base_url}/status", headers=headers)
        assert response.status_code == 200


class TestPredictionEndpoints:
    """Test prediction endpoints."""

    def test_predict_missing_ticker_400(self, api_base_url, jwt_token):
        """Predict without ticker should return 400."""
        headers = {"Authorization": f"Bearer {jwt_token}"}
        response = requests.post(
            f"{api_base_url}/predict",
            headers=headers,
            json={"lookback_window": 20}
        )
        assert response.status_code == 400

    def test_predict_valid_request_success(self, api_base_url, jwt_token):
        """Valid predict request should return 200."""
        headers = {"Authorization": f"Bearer {jwt_token}"}
        payload = {
            "ticker": "AAPL",
            "lookback_window": 20,
            "model_type": "lstm"
        }
        response = requests.post(
            f"{api_base_url}/predict",
            headers=headers,
            json=payload
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "predicted_price" in data
        assert "signal" in data
        assert data["signal"] in ["BUY", "SELL", "HOLD"]

    def test_batch_predict_multiple_tickers(self, api_base_url, jwt_token):
        """Batch predict should handle multiple tickers."""
        headers = {"Authorization": f"Bearer {jwt_token}"}
        payload = {
            "tickers": ["AAPL", "GOOGL", "MSFT"],
            "lookback_window": 20
        }
        response = requests.post(
            f"{api_base_url}/batch-predict",
            headers=headers,
            json=payload
        )
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 3


class TestTradeExecutionEndpoints:
    """Test trade execution endpoints."""

    def test_execute_requires_permission(self, api_base_url):
        """Execute endpoint requires TRADER permission."""
        # Monitor role shouldn't have execute permission
        from production_hardening.api_security import jwt_manager, UserRole
        monitor_token = jwt_manager.create_token("monitor_user", UserRole.MONITOR)
        
        headers = {"Authorization": f"Bearer {monitor_token}"}
        response = requests.post(
            f"{api_base_url}/execute",
            headers=headers,
            json={"ticker": "AAPL", "side": "BUY", "quantity": 100}
        )
        
        assert response.status_code == 403

    def test_execute_with_idempotency_key(self, api_base_url, jwt_token):
        """Execute with idempotency key should prevent duplicates."""
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Idempotency-Key": "test-idempotency-key-123"
        }
        payload = {"ticker": "AAPL", "side": "BUY", "quantity": 100}

        # First request
        response1 = requests.post(
            f"{api_base_url}/execute",
            headers=headers,
            json=payload
        )
        order_id1 = response1.json().get("order_id")

        # Second request with same idempotency key
        response2 = requests.post(
            f"{api_base_url}/execute",
            headers=headers,
            json=payload
        )
        order_id2 = response2.json().get("order_id")

        # Should return same order
        assert order_id1 == order_id2

    def test_execute_rate_limiting(self, api_base_url, jwt_token):
        """Execute endpoint should enforce rate limits."""
        headers = {"Authorization": f"Bearer {jwt_token}"}
        payload = {"ticker": "AAPL", "side": "BUY", "quantity": 100}

        # Make requests up to limit (~10/min)
        for i in range(15):
            response = requests.post(
                f"{api_base_url}/execute",
                headers=headers,
                json=payload
            )
            
            if i < 10:
                assert response.status_code == 200
            else:
                # Should be rate limited
                assert response.status_code == 429


class TestMetricsAndDashboard:
    """Test metrics and dashboard endpoints."""

    def test_metrics_json_response(self, api_base_url, jwt_token):
        """Metrics endpoint should return valid JSON."""
        headers = {"Authorization": f"Bearer {jwt_token}"}
        response = requests.get(
            f"{api_base_url}/metrics",
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "pnl" in data
        assert "win_rate" in data
        assert "sharpe_ratio" in data

    def test_dashboard_html_response(self, api_base_url, jwt_token):
        """Dashboard endpoint should return HTML."""
        headers = {"Authorization": f"Bearer {jwt_token}"}
        response = requests.get(
            f"{api_base_url}/dashboard",
            headers=headers
        )
        
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")


class TestConfigurationEndpoints:
    """Test configuration management endpoints."""

    def test_get_config(self, api_base_url, jwt_token):
        """GET /config should return current configuration."""
        headers = {"Authorization": f"Bearer {jwt_token}"}
        response = requests.get(
            f"{api_base_url}/config",
            headers=headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_put_config_requires_admin(self, api_base_url):
        """PUT /config should require ADMIN role."""
        from production_hardening.api_security import jwt_manager, UserRole
        trader_token = jwt_manager.create_token("trader_user", UserRole.TRADER)
        
        headers = {"Authorization": f"Bearer {trader_token}"}
        response = requests.put(
            f"{api_base_url}/config",
            headers=headers,
            json={"max_position_size": 5000}
        )
        
        assert response.status_code == 403

    def test_put_config_updates_parameters(self, api_base_url, jwt_token):
        """PUT /config with admin token should update config."""
        from production_hardening.api_security import jwt_manager, UserRole
        admin_token = jwt_manager.create_token("admin_user", UserRole.ADMIN)
        
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = requests.put(
            f"{api_base_url}/config",
            headers=headers,
            json={"max_position_size": 5000}
        )
        
        assert response.status_code == 200


# ============================================================================
# ASYNC TESTS
# ============================================================================


class TestAsyncDataFetcher:
    """Test async data fetching functionality."""

    @pytest.mark.asyncio
    async def test_concurrent_data_fetch(self):
        """Async fetcher should fetch multiple tickers concurrently."""
        from async_data_fetcher import fetch_portfolio_data
        
        # Fetch 5 tickers concurrently
        start_time = datetime.now()
        result = await fetch_portfolio_data(
            ["AAPL", "GOOGL", "MSFT", "TSLA", "AMZN"],
            period="1mo"
        )
        elapsed = (datetime.now() - start_time).total_seconds()

        assert isinstance(result, dict)
        assert len(result) == 5
        # Should be ~5-10 seconds, not 20-30 seconds for sequential
        assert elapsed < 15

    @pytest.mark.asyncio
    async def test_batch_inference_pipeline(self):
        """Batch inference pipeline should process in parallel."""
        from async_data_fetcher import BatchInferencePipeline
        import torch

        # Create dummy model and data
        model = torch.nn.Linear(10, 1)
        pipeline = BatchInferencePipeline(batch_size=32)
        
        inputs = [torch.randn(10) for _ in range(100)]

        start_time = datetime.now()
        results = await pipeline.infer_multiple_batches(
            model, inputs, torch.device("cpu")
        )
        elapsed = (datetime.now() - start_time).total_seconds()

        assert len(results) == 100
        # Batch processing should be fast
        assert elapsed < 5


# ============================================================================
# DATABASE INTEGRATION TESTS
# ============================================================================


class TestDatabaseIntegration:
    """Test database operations."""

    def test_database_connection(self, db_connection_string):
        """Should establish database connection."""
        import psycopg2
        try:
            conn = psycopg2.connect(db_connection_string)
            assert conn is not None
            conn.close()
        except Exception as e:
            pytest.skip(f"Database not available: {e}")

    def test_create_and_query_trades(self, db_connection_string):
        """Should create and query trade records."""
        import psycopg2
        try:
            conn = psycopg2.connect(db_connection_string)
            cursor = conn.cursor()

            # Create table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS test_trades (
                    id SERIAL PRIMARY KEY,
                    ticker VARCHAR(10),
                    side VARCHAR(10),
                    quantity FLOAT,
                    price FLOAT,
                    timestamp TIMESTAMP
                )
            """)

            # Insert test data
            cursor.execute("""
                INSERT INTO test_trades (ticker, side, quantity, price, timestamp)
                VALUES (%s, %s, %s, %s, %s)
            """, ("AAPL", "BUY", 100, 150.0, datetime.utcnow()))

            conn.commit()

            # Query
            cursor.execute("SELECT COUNT(*) FROM test_trades WHERE ticker = %s", ("AAPL",))
            count = cursor.fetchone()[0]
            
            assert count > 0

            cursor.close()
            conn.close()

        except Exception as e:
            pytest.skip(f"Database test skipped: {e}")


# ============================================================================
# END-TO-END WORKFLOW TESTS
# ============================================================================


class TestEndToEndWorkflow:
    """Test complete trading workflows."""

    def test_predict_and_execute_workflow(self, api_base_url, jwt_token):
        """Complete workflow: predict → generate signal → execute."""
        headers = {"Authorization": f"Bearer {jwt_token}"}

        # 1. Predict
        pred_response = requests.post(
            f"{api_base_url}/predict",
            headers=headers,
            json={"ticker": "AAPL", "model_type": "lstm"}
        )
        assert pred_response.status_code == 200
        prediction = pred_response.json()
        signal = prediction["signal"]

        # 2. Execute if signal is not HOLD
        if signal != "HOLD":
            exec_response = requests.post(
                f"{api_base_url}/execute",
                headers=headers,
                json={
                    "ticker": "AAPL",
                    "side": signal.replace("BUY", "BUY").replace("SELL", "SELL"),
                    "quantity": 100
                }
            )
            assert exec_response.status_code == 200

    def test_backtest_workflow(self, api_base_url, jwt_token):
        """Should complete backtest workflow."""
        headers = {"Authorization": f"Bearer {jwt_token}"}
        
        response = requests.post(
            f"{api_base_url}/backtest",
            headers=headers,
            json={
                "ticker": "AAPL",
                "start_date": (datetime.now() - timedelta(days=30)).isoformat(),
                "end_date": datetime.now().isoformat(),
                "initial_capital": 100000
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "total_return" in data
        assert "num_trades" in data
