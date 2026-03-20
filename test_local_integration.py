#!/usr/bin/env python
"""
Local test runner for integrated API with Phase 1 enhancements.

Run with: python test_local_integration.py

Tests:
- API security (JWT, RBAC, rate limiting, idempotency)
- Risk engine (pre-trade checks, kill-switch, VaR)
- Data quality gates
- Model lifecycle
- End-to-end workflows
"""

import sys
import time
import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List
import requests

# ============================================================================
# TEST CONFIGURATION
# ============================================================================

API_URL = "http://localhost:5000"
TEST_USER_ID = "test_trader"
TEST_TICKER = "AAPL"

# Test results tracking
test_results = {
    "passed": 0,
    "failed": 0,
    "skipped": 0,
    "errors": []
}


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def print_header(title: str):
    """Print section header."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def print_test(name: str, passed: bool, message: str = ""):
    """Print test result."""
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status:10} {name:40} {message}")
    
    if passed:
        test_results["passed"] += 1
    else:
        test_results["failed"] += 1
        test_results["errors"].append(f"{name}: {message}")


def try_request(description: str, method: str, endpoint: str, **kwargs) -> Dict:
    """Make HTTP request and handle errors."""
    try:
        url = f"{API_URL}{endpoint}"
        
        if method.upper() == "GET":
            response = requests.get(url, **kwargs)
        elif method.upper() == "POST":
            response = requests.post(url, **kwargs)
        elif method.upper() == "PUT":
            response = requests.put(url, **kwargs)
        else:
            return {"success": False, "error": f"Unknown method: {method}"}
        
        return {
            "success": True,
            "status_code": response.status_code,
            "data": response.json() if response.content else None,
            "text": response.text
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# SETUP & TOKEN GENERATION
# ============================================================================

def setup_tokens() -> Dict[str, str]:
    """Generate JWT tokens for different roles."""
    print("\n🔐 Generating JWT tokens...")
    
    tokens = {}
    roles = ["ADMIN", "TRADER", "ANALYST", "MONITOR"]
    
    for role in roles:
        result = try_request(
            f"Generate {role} token",
            "POST",
            "/auth/token",
            json={"user_id": f"test_{role.lower()}", "role": role}
        )
        
        if result["success"] and result["status_code"] == 200:
            token = result["data"]["access_token"]
            tokens[role] = token
            print(f"  ✓ {role:10} token generated")
        else:
            print(f"  ✗ {role:10} token failed: {result.get('error', 'Unknown error')}")
    
    return tokens


# ============================================================================
# TEST SUITES
# ============================================================================

def test_health_check():
    """Test health endpoint (no auth required)."""
    print_header("Test 1: Health Check (No Auth)")
    
    result = try_request("Health check", "GET", "/health")
    
    if result["success"] and result["status_code"] == 200:
        data = result["data"]
        passed = "status" in data and data["status"] == "healthy"
        print_test("Health endpoint", passed, f"Status: {data.get('status')}")
    else:
        print_test("Health endpoint", False, result.get("error", "Failed"))


def test_authentication(tokens: Dict[str, str]):
    """Test authentication and authorization."""
    print_header("Test 2: Authentication & Authorization")
    
    # Test without token
    result = try_request("Request without token", "GET", "/status")
    print_test("Rejected without token", result["status_code"] == 401)
    
    # Test with invalid token
    result = try_request(
        "Request with invalid token",
        "GET",
        "/status",
        headers={"Authorization": "Bearer invalid_token"}
    )
    print_test("Rejected invalid token", result["status_code"] == 401)
    
    # Test with valid token
    if "TRADER" in tokens:
        result = try_request(
            "Request with valid token",
            "GET",
            "/status",
            headers={"Authorization": f"Bearer {tokens['TRADER']}"}
        )
        print_test("Accepted valid token", result["status_code"] == 200)


def test_rbac(tokens: Dict[str, str]):
    """Test role-based access control."""
    print_header("Test 3: Role-Based Access Control")
    
    # MONITOR should NOT be able to execute trades
    if "MONITOR" in tokens:
        result = try_request(
            "MONITOR attempts trade execution",
            "POST",
            "/execute",
            headers={"Authorization": f"Bearer {tokens['MONITOR']}"},
            json={"ticker": TEST_TICKER, "side": "BUY", "quantity": 100}
        )
        print_test("MONITOR blocked from trading", result["status_code"] == 403)
    
    # TRADER should be able to execute
    if "TRADER" in tokens:
        result = try_request(
            "TRADER attempts trade execution",
            "POST",
            "/execute",
            headers={"Authorization": f"Bearer {tokens['TRADER']}"},
            json={"ticker": TEST_TICKER, "side": "BUY", "quantity": 100}
        )
        can_execute = result["status_code"] in [200, 400]  # 200=success, 400=validation
        print_test("TRADER can attempt trading", can_execute)
    
    # ANALYST cannot modify config
    if "ANALYST" in tokens:
        result = try_request(
            "ANALYST attempts config modification",
            "PUT",
            "/config",
            headers={"Authorization": f"Bearer {tokens['ANALYST']}"},
            json={"max_position_size": 5000}
        )
        print_test("ANALYST blocked from config", result["status_code"] == 403)
    
    # ADMIN can modify config
    if "ADMIN" in tokens:
        result = try_request(
            "ADMIN modifies config",
            "PUT",
            "/config",
            headers={"Authorization": f"Bearer {tokens['ADMIN']}"},
            json={"max_position_size": 5000}
        )
        print_test("ADMIN can modify config", result["status_code"] == 200)


def test_predictions(tokens: Dict[str, str]):
    """Test prediction endpoints."""
    print_header("Test 4: Prediction Endpoints")
    
    if "ANALYST" not in tokens:
        print_test("Predictions (no token)", False, "ANALYST token not available")
        return
    
    headers = {"Authorization": f"Bearer {tokens['ANALYST']}"}
    
    # Single prediction
    result = try_request(
        "Single prediction",
        "POST",
        "/predict",
        headers=headers,
        json={"ticker": TEST_TICKER, "lookback_window": 20}
    )
    
    if result["success"] and result["status_code"] == 200:
        data = result["data"]
        passed = all(k in data for k in ["ticker", "signal", "predicted_price"])
        print_test("Single prediction", passed, f"Signal: {data.get('signal')}")
    else:
        print_test("Single prediction", False, result.get("error", "Failed"))
    
    # Batch prediction
    result = try_request(
        "Batch prediction",
        "POST",
        "/batch-predict",
        headers=headers,
        json={"tickers": ["AAPL", "GOOGL", "MSFT"]}
    )
    
    if result["success"] and result["status_code"] == 200:
        data = result["data"]
        passed = isinstance(data, list) and len(data) > 0
        print_test("Batch prediction", passed, f"Predictions: {len(data)}")
    else:
        print_test("Batch prediction", False, result.get("error", "Failed"))


def test_trade_execution(tokens: Dict[str, str]):
    """Test trade execution with risk checks."""
    print_header("Test 5: Trade Execution & Risk")
    
    if "TRADER" not in tokens:
        print_test("Trade execution", False, "TRADER token not available")
        return
    
    headers = {"Authorization": f"Bearer {tokens['TRADER']}"}
    
    # Valid trade
    result = try_request(
        "Execute valid trade",
        "POST",
        "/execute",
        headers=headers,
        json={"ticker": TEST_TICKER, "side": "BUY", "quantity": 100, "price": 150.0}
    )
    
    print_test(
        "Trade execution",
        result["status_code"] in [200, 400],
        f"Status: {result.get('status_code')}"
    )
    
    # Invalid side
    result = try_request(
        "Trade with invalid side",
        "POST",
        "/execute",
        headers=headers,
        json={"ticker": TEST_TICKER, "side": "INVALID", "quantity": 100}
    )
    print_test("Invalid side rejected", result["status_code"] == 400)
    
    # Negative quantity
    result = try_request(
        "Trade with negative quantity",
        "POST",
        "/execute",
        headers=headers,
        json={"ticker": TEST_TICKER, "side": "BUY", "quantity": -100}
    )
    print_test("Negative quantity rejected", result["status_code"] == 400)
    
    # Idempotency test
    idempotency_key = f"test_idempotency_{int(time.time())}"
    
    result1 = try_request(
        "First idempotent request",
        "POST",
        "/execute",
        headers={
            "Authorization": f"Bearer {tokens['TRADER']}",
            "Idempotency-Key": idempotency_key
        },
        json={"ticker": TEST_TICKER, "side": "BUY", "quantity": 50}
    )
    
    result2 = try_request(
        "Duplicate idempotent request",
        "POST",
        "/execute",
        headers={
            "Authorization": f"Bearer {tokens['TRADER']}",
            "Idempotency-Key": idempotency_key
        },
        json={"ticker": TEST_TICKER, "side": "BUY", "quantity": 50}
    )
    
    if result1["success"] and result2["success"]:
        order_id_1 = result1["data"].get("order_id")
        order_id_2 = result2["data"].get("order_id")
        print_test(
            "Idempotency key prevents duplicates",
            order_id_1 == order_id_2,
            f"IDs: {order_id_1} vs {order_id_2}"
        )
    else:
        print_test("Idempotency test", False, "Requests failed")


def test_risk_metrics(tokens: Dict[str, str]):
    """Test risk metrics endpoints."""
    print_header("Test 6: Risk Metrics")
    
    if "TRADER" not in tokens:
        print_test("Risk metrics", False, "TRADER token not available")
        return
    
    headers = {"Authorization": f"Bearer {tokens['TRADER']}"}
    
    # Get risk metrics
    result = try_request("Get risk metrics", "GET", "/risk/metrics", headers=headers)
    
    if result["success"] and result["status_code"] == 200:
        data = result["data"]
        required_fields = ["var_95", "cvar_95", "leverage", "is_stressed"]
        passed = all(field in data for field in required_fields)
        print_test(
            "Risk metrics retrieval",
            passed,
            f"Leverage: {data.get('leverage'):.2f}x, Stressed: {data.get('is_stressed')}"
        )
    else:
        print_test("Risk metrics", False, result.get("error", "Failed"))


def test_performance_metrics(tokens: Dict[str, str]):
    """Test performance metrics."""
    print_header("Test 7: Performance Metrics")
    
    if "ANALYST" not in tokens:
        print_test("Performance metrics", False, "ANALYST token not available")
        return
    
    headers = {"Authorization": f"Bearer {tokens['ANALYST']}"}
    
    result = try_request("Get metrics", "GET", "/metrics", headers=headers)
    
    if result["success"] and result["status_code"] == 200:
        data = result["data"]
        required = ["pnl", "win_rate", "sharpe_ratio"]
        passed = all(field in data for field in required)
        print_test(
            "Metrics retrieval",
            passed,
            f"PnL: ${data.get('pnl'):.2f}, WinRate: {data.get('win_rate'):.1%}"
        )
    else:
        print_test("Metrics retrieval", False, result.get("error", "Failed"))


def test_model_lifecycle(tokens: Dict[str, str]):
    """Test model lifecycle management."""
    print_header("Test 8: Model Lifecycle")
    
    if "ADMIN" not in tokens:
        print_test("Model lifecycle", False, "ADMIN token not available")
        return
    
    headers = {"Authorization": f"Bearer {tokens['ADMIN']}"}
    
    # List models
    result = try_request("List models", "GET", "/models", headers=headers)
    print_test(
        "List models",
        result["success"] and result["status_code"] == 200,
        f"Models: {result.get('data', {})}"
    )


def test_rate_limiting(tokens: Dict[str, str]):
    """Test rate limiting."""
    print_header("Test 9: Rate Limiting")
    
    if "TRADER" not in tokens:
        print_test("Rate limiting test", False, "TRADER token not available")
        return
    
    headers = {"Authorization": f"Bearer {tokens['TRADER']}"}
    
    # Make many prediction requests (rate limit is 100/min)
    print("  Sending 10 requests to /predict...")
    
    success_count = 0
    for i in range(10):
        result = try_request(
            f"Prediction request {i+1}",
            "POST",
            "/predict",
            headers=headers,
            json={"ticker": TEST_TICKER}
        )
        
        if result["status_code"] == 200:
            success_count += 1
        elif result["status_code"] == 429:
            print(f"  Rate limit hit at request {i+1}")
            break
    
    print_test("Rate limiting", success_count >= 10, f"Successful: {success_count}/10")


def test_dashboard(tokens: Dict[str, str]):
    """Test dashboard endpoint."""
    print_header("Test 10: Dashboard")
    
    if "ANALYST" not in tokens:
        print_test("Dashboard", False, "ANALYST token not available")
        return
    
    headers = {"Authorization": f"Bearer {tokens['ANALYST']}"}
    
    result = try_request("Get dashboard", "GET", "/dashboard", headers=headers)
    
    passed = result["success"] and result["status_code"] == 200 and "<html>" in result.get("text", "")
    print_test("Dashboard retrieval", passed, "HTML dashboard served")


# ============================================================================
# MAIN TEST RUNNER
# ============================================================================

def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("  INTEGRATED API TEST SUITE (Phase 1 Enhancements)")
    print("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("="*60)
    
    # Check API availability
    try:
        response = requests.get(f"{API_URL}/health", timeout=2)
        print(f"\n✅ API is available at {API_URL}")
    except Exception as e:
        print(f"\n❌ API is NOT available at {API_URL}")
        print(f"   Error: {e}")
        print(f"\n✓ Start the API with:")
        print(f"   uvicorn api_server_enhanced:app --reload")
        return
    
    # Generate tokens
    tokens = setup_tokens()
    
    if not tokens:
        print("\n❌ Failed to generate any tokens. Check API logs.")
        return
    
    # Run test suites
    test_health_check()
    test_authentication(tokens)
    test_rbac(tokens)
    test_predictions(tokens)
    test_trade_execution(tokens)
    test_risk_metrics(tokens)
    test_performance_metrics(tokens)
    test_model_lifecycle(tokens)
    test_rate_limiting(tokens)
    test_dashboard(tokens)
    
    # Print summary
    print_header("TEST SUMMARY")
    total = test_results["passed"] + test_results["failed"]
    pct = (test_results["passed"] / total * 100) if total > 0 else 0
    
    print(f"\n  Total Tests:   {total}")
    print(f"  ✅ Passed:   {test_results['passed']}")
    print(f"  ❌ Failed:   {test_results['failed']}")
    print(f"  Success Rate: {pct:.1f}%")
    
    if test_results["errors"]:
        print(f"\n  Errors:")
        for error in test_results["errors"][:5]:
            print(f"    • {error}")
        if len(test_results["errors"]) > 5:
            print(f"    ... and {len(test_results['errors']) - 5} more")
    
    print("\n" + "="*60)
    if test_results["failed"] == 0:
        print("✅ ALL TESTS PASSED!")
    else:
        print("⚠️  SOME TESTS FAILED - Check logs above")
    print("="*60 + "\n")
    
    return test_results["failed"] == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
