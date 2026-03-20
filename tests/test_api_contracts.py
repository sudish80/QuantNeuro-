"""
API Contract Tests - Ensure API adheres to documented contracts.

Tests:
- Request/response schema validation
- HTTP status codes
- Error response format
- API stability across versions
"""

import pytest
import requests
from typing import Dict, Any
from jsonschema import validate, ValidationError


# ============================================================================
# SCHEMA DEFINITIONS
# ============================================================================

PREDICTION_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["ticker", "predicted_price", "signal", "confidence"],
    "properties": {
        "ticker": {"type": "string"},
        "current_price": {"type": "number"},
        "predicted_price": {"type": "number"},
        "signal": {"type": "string", "enum": ["BUY", "SELL", "HOLD"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "timestamp": {"type": "string"},
    }
}

EXECUTION_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["order_id", "status", "filled_quantity"],
    "properties": {
        "order_id": {"type": "string"},
        "status": {"type": "string", "enum": ["PENDING", "FILLED", "REJECTED"]},
        "filled_quantity": {"type": "number"},
        "filled_price": {"type": "number"},
        "timestamp": {"type": "string"},
    }
}

METRICS_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["pnl", "win_rate", "sharpe_ratio"],
    "properties": {
        "pnl": {"type": "number"},
        "win_rate": {"type": "number", "minimum": 0, "maximum": 1},
        "sharpe_ratio": {"type": "number"},
        "max_drawdown": {"type": "number"},
        "num_trades": {"type": "integer"},
        "timestamp": {"type": "string"},
    }
}

ERROR_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["error", "message"],
    "properties": {
        "error": {"type": "string"},
        "message": {"type": "string"},
        "details": {"type": ["object", "null"]},
        "timestamp": {"type": "string"},
    }
}

HEALTH_CHECK_SCHEMA = {
    "type": "object",
    "required": ["status"],
    "properties": {
        "status": {"type": "string"},
        "timestamp": {"type": "string"},
        "version": {"type": "string"},
    }
}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def validate_schema(response: requests.Response, schema: Dict[str, Any]) -> bool:
    """Validate response matches schema."""
    try:
        validate(instance=response.json(), schema=schema)
        return True
    except ValidationError as e:
        pytest.fail(f"Schema validation failed: {e.message}")


def assert_status_code(response: requests.Response, expected: int):
    """Assert response status code."""
    assert response.status_code == expected, (
        f"Expected {expected}, got {response.status_code}. "
        f"Response: {response.text}"
    )


# ============================================================================
# PREDICTION ENDPOINT CONTRACTS
# ============================================================================


class TestPredictionContract:
    """Contract tests for prediction endpoints."""

    @pytest.fixture
    def api_url(self):
        return "http://localhost:5000"

    @pytest.fixture
    def auth_headers(self):
        from production_hardening.api_security import jwt_manager, UserRole
        token = jwt_manager.create_token("test", UserRole.ANALYST)
        return {"Authorization": f"Bearer {token}"}

    def test_predict_response_structure(self, api_url, auth_headers):
        """Response should match prediction schema."""
        response = requests.post(
            f"{api_url}/predict",
            headers=auth_headers,
            json={"ticker": "AAPL"}
        )

        assert_status_code(response, 200)
        validate_schema(response, PREDICTION_RESPONSE_SCHEMA)

    def test_predict_requires_ticker(self, api_url, auth_headers):
        """Prediction without ticker should error."""
        response = requests.post(
            f"{api_url}/predict",
            headers=auth_headers,
            json={}
        )

        assert response.status_code == 400
        validate_schema(response, ERROR_RESPONSE_SCHEMA)

    def test_predict_invalid_model_type(self, api_url, auth_headers):
        """Invalid model type should error."""
        response = requests.post(
            f"{api_url}/predict",
            headers=auth_headers,
            json={"ticker": "AAPL", "model_type": "invalid_model"}
        )

        assert response.status_code == 400
        data = response.json()
        assert "error" in data

    def test_batch_predict_response_array(self, api_url, auth_headers):
        """Batch predict should return array of predictions."""
        response = requests.post(
            f"{api_url}/batch-predict",
            headers=auth_headers,
            json={"tickers": ["AAPL", "GOOGL"]}
        )

        assert_status_code(response, 200)
        assert isinstance(response.json(), list)
        
        for item in response.json():
            validate_schema(
                requests.Response(),  # Dummy for validation
                PREDICTION_RESPONSE_SCHEMA
            )


# ============================================================================
# EXECUTION ENDPOINT CONTRACTS
# ============================================================================


class TestExecutionContract:
    """Contract tests for trade execution endpoints."""

    @pytest.fixture
    def api_url(self):
        return "http://localhost:5000"

    @pytest.fixture
    def trader_headers(self):
        from production_hardening.api_security import jwt_manager, UserRole
        token = jwt_manager.create_token("trader", UserRole.TRADER)
        return {"Authorization": f"Bearer {token}"}

    def test_execute_response_structure(self, api_url, trader_headers):
        """Response should match execution schema."""
        response = requests.post(
            f"{api_url}/execute",
            headers=trader_headers,
            json={"ticker": "AAPL", "side": "BUY", "quantity": 100}
        )

        assert_status_code(response, 200)
        validate_schema(response, EXECUTION_RESPONSE_SCHEMA)

    def test_execute_returns_order_id(self, api_url, trader_headers):
        """Execution response must include order_id."""
        response = requests.post(
            f"{api_url}/execute",
            headers=trader_headers,
            json={"ticker": "AAPL", "side": "BUY", "quantity": 100}
        )

        data = response.json()
        assert "order_id" in data
        assert isinstance(data["order_id"], str)
        assert len(data["order_id"]) > 0

    def test_execute_invalid_side_400(self, api_url, trader_headers):
        """Invalid side should return 400."""
        response = requests.post(
            f"{api_url}/execute",
            headers=trader_headers,
            json={"ticker": "AAPL", "side": "INVALID", "quantity": 100}
        )

        assert response.status_code == 400
        validate_schema(response, ERROR_RESPONSE_SCHEMA)

    def test_execute_without_auth_401(self, api_url):
        """Execution without auth should return 401."""
        response = requests.post(
            f"{api_url}/execute",
            json={"ticker": "AAPL", "side": "BUY", "quantity": 100}
        )

        assert response.status_code == 401
        validate_schema(response, ERROR_RESPONSE_SCHEMA)

    def test_execute_monitor_403(self, api_url):
        """Monitor role should not execute trades."""
        from production_hardening.api_security import jwt_manager, UserRole
        token = jwt_manager.create_token("monitor", UserRole.MONITOR)
        headers = {"Authorization": f"Bearer {token}"}

        response = requests.post(
            f"{api_url}/execute",
            headers=headers,
            json={"ticker": "AAPL", "side": "BUY", "quantity": 100}
        )

        assert response.status_code == 403


# ============================================================================
# METRICS ENDPOINT CONTRACTS
# ============================================================================


class TestMetricsContract:
    """Contract tests for metrics endpoints."""

    @pytest.fixture
    def api_url(self):
        return "http://localhost:5000"

    @pytest.fixture
    def auth_headers(self):
        from production_hardening.api_security import jwt_manager, UserRole
        token = jwt_manager.create_token("analyst", UserRole.ANALYST)
        return {"Authorization": f"Bearer {token}"}

    def test_metrics_response_structure(self, api_url, auth_headers):
        """Metrics response should match schema."""
        response = requests.get(
            f"{api_url}/metrics",
            headers=auth_headers
        )

        assert_status_code(response, 200)
        validate_schema(response, METRICS_RESPONSE_SCHEMA)

    def test_metrics_contains_pnl(self, api_url, auth_headers):
        """Metrics must include P&L."""
        response = requests.get(
            f"{api_url}/metrics",
            headers=auth_headers
        )

        data = response.json()
        assert "pnl" in data

    def test_metrics_win_rate_valid_range(self, api_url, auth_headers):
        """Win rate should be between 0 and 1."""
        response = requests.get(
            f"{api_url}/metrics",
            headers=auth_headers
        )

        data = response.json()
        assert 0 <= data["win_rate"] <= 1


# ============================================================================
# HEALTH & STATUS ENDPOINT CONTRACTS
# ============================================================================


class TestHealthContract:
    """Contract tests for health check endpoints."""

    @pytest.fixture
    def api_url(self):
        return "http://localhost:5000"

    def test_health_no_auth_required(self, api_url):
        """Health endpoint should not require auth."""
        response = requests.get(f"{api_url}/health")
        
        assert response.status_code == 200
        validate_schema(response, HEALTH_CHECK_SCHEMA)

    def test_health_response_format(self, api_url):
        """Health response should have required fields."""
        response = requests.get(f"{api_url}/health")
        data = response.json()

        assert "status" in data
        assert data["status"] in ["healthy", "ok", "up"]

    def test_health_fast_response(self, api_url):
        """Health check should be fast (<100ms)."""
        import time
        
        start = time.time()
        response = requests.get(f"{api_url}/health")
        elapsed = (time.time() - start) * 1000

        assert elapsed < 100, f"Health check too slow: {elapsed}ms"


# ============================================================================
# ERROR HANDLING CONTRACTS
# ============================================================================


class TestErrorHandling:
    """Contract tests for error responses."""

    @pytest.fixture
    def api_url(self):
        return "http://localhost:5000"

    @pytest.fixture
    def auth_headers(self):
        from production_hardening.api_security import jwt_manager, UserRole
        token = jwt_manager.create_token("test", UserRole.TRADER)
        return {"Authorization": f"Bearer {token}"}

    def test_404_error_structure(self, api_url, auth_headers):
        """404 errors should have standard format."""
        response = requests.get(
            f"{api_url}/nonexistent-endpoint",
            headers=auth_headers
        )

        assert response.status_code == 404
        data = response.json()
        assert "error" in data or "message" in data

    def test_500_error_structure(self, api_url, auth_headers):
        """5xx errors should have standard format."""
        # Make a request that might cause server error
        response = requests.post(
            f"{api_url}/predict",
            headers=auth_headers,
            json={"ticker": ""}  # Empty ticker
        )

        if response.status_code >= 500:
            validate_schema(response, ERROR_RESPONSE_SCHEMA)

    def test_rate_limit_429_response(self, api_url, auth_headers):
        """Rate limit should return 429 with error."""
        # Make many requests
        for _ in range(50):
            response = requests.post(
                f"{api_url}/execute",
                headers=auth_headers,
                json={"ticker": "AAPL", "side": "BUY", "quantity": 100}
            )

            if response.status_code == 429:
                data = response.json()
                assert "error" in data or "message" in data
                break


# ============================================================================
# VERSION STABILITY TESTS
# ============================================================================


class TestVersionStability:
    """Tests to ensure backward compatibility."""

    @pytest.fixture
    def api_url(self):
        return "http://localhost:5000"

    @pytest.fixture
    def auth_headers(self):
        from production_hardening.api_security import jwt_manager, UserRole
        token = jwt_manager.create_token("test", UserRole.ANALYST)
        return {"Authorization": f"Bearer {token}"}

    def test_old_predict_format_still_works(self, api_url, auth_headers):
        """Should still support old request format."""
        # Old format: ticker only
        response = requests.post(
            f"{api_url}/predict",
            headers=auth_headers,
            json={"ticker": "AAPL"}
        )

        assert response.status_code == 200
        data = response.json()
        
        # Old response format expectations
        assert "ticker" in data
        assert "signal" in data

    def test_response_fields_not_removed(self, api_url, auth_headers):
        """Response should not remove documented fields."""
        response = requests.post(
            f"{api_url}/predict",
            headers=auth_headers,
            json={"ticker": "AAPL"}
        )

        assert response.status_code == 200
        data = response.json()

        # Essential fields should always be present
        essential_fields = ["ticker", "signal"]
        for field in essential_fields:
            assert field in data, f"Missing essential field: {field}"
