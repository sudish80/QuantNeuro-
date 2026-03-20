"""
API security and governance layer.

Provides:
- JWT token management and validation
- Role-based access control (RBAC)
- Rate limiting per user/endpoint
- Request signing for critical operations
- Idempotency key tracking for mutations
- Audit logging for sensitive operations
"""

import os
import hashlib
import hmac
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Callable, Any
from functools import wraps
from enum import Enum

import jwt
from fastapi import HTTPException, Depends, Header, Request
from fastapi.security import HTTPBearer, HTTPAuthCredentials

# ============================================================================
# ENUMS
# ============================================================================

class UserRole(str, Enum):
    """User roles for RBAC."""
    ADMIN = "admin"
    TRADER = "trader"
    ANALYST = "analyst"
    MONITOR = "monitor"


class PermissionType(str, Enum):
    """Permission types."""
    PREDICT = "predict"
    EXECUTE_TRADE = "execute_trade"
    MODIFY_CONFIG = "modify_config"
    VIEW_METRICS = "view_metrics"
    MANAGE_USERS = "manage_users"


# ============================================================================
# ROLE-BASED PERMISSIONS
# ============================================================================

ROLE_PERMISSIONS: Dict[UserRole, List[PermissionType]] = {
    UserRole.ADMIN: [
        PermissionType.PREDICT,
        PermissionType.EXECUTE_TRADE,
        PermissionType.MODIFY_CONFIG,
        PermissionType.VIEW_METRICS,
        PermissionType.MANAGE_USERS,
    ],
    UserRole.TRADER: [
        PermissionType.PREDICT,
        PermissionType.EXECUTE_TRADE,
        PermissionType.VIEW_METRICS,
    ],
    UserRole.ANALYST: [
        PermissionType.PREDICT,
        PermissionType.VIEW_METRICS,
    ],
    UserRole.MONITOR: [
        PermissionType.VIEW_METRICS,
    ],
}


# ============================================================================
# TOKEN MANAGEMENT
# ============================================================================

class JWTTokenManager:
    """Manages JWT token creation and validation."""

    def __init__(
        self,
        secret_key: Optional[str] = None,
        algorithm: str = "HS256",
        expiration_hours: int = 24,
    ):
        self.secret_key = secret_key or os.getenv(
            "JWT_SECRET_KEY", "dev-secret-key-change-in-production"
        )
        self.algorithm = algorithm
        self.expiration_hours = expiration_hours

    def create_token(
        self, user_id: str, role: UserRole, expires_in_hours: Optional[int] = None
    ) -> str:
        """Create a JWT token for the given user."""
        payload = {
            "user_id": user_id,
            "role": role.value,
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow()
            + timedelta(hours=expires_in_hours or self.expiration_hours),
            "jti": str(uuid.uuid4()),  # Token ID for revocation tracking
        }
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def validate_token(self, token: str) -> Dict[str, Any]:
        """Validate and decode a JWT token."""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token")

    def get_user_from_token(self, token: str) -> tuple[str, UserRole]:
        """Extract user_id and role from token."""
        payload = self.validate_token(token)
        return payload["user_id"], UserRole(payload["role"])


# ============================================================================
# RATE LIMITING
# ============================================================================

class RateLimiter:
    """Token bucket rate limiter with per-user and per-endpoint tracking."""

    def __init__(self, default_requests_per_minute: int = 60):
        self.default_rps_per_minute = default_requests_per_minute
        # {user_id: {endpoint: [timestamps]}}
        self.request_history: Dict[str, Dict[str, List[datetime]]] = {}
        self.endpoint_limits: Dict[str, int] = {
            "/execute": 10,  # Critical endpoint: 10/min
            "/predict": 100,  # Prediction: 100/min
            "/metrics": 30,  # Metrics: 30/min
        }

    def is_rate_limited(self, user_id: str, endpoint: str) -> bool:
        """Check if user has exceeded rate limit for endpoint."""
        if user_id not in self.request_history:
            self.request_history[user_id] = {}

        if endpoint not in self.request_history[user_id]:
            self.request_history[user_id][endpoint] = []

        now = datetime.utcnow()
        cutoff = now - timedelta(minutes=1)

        # Clean old requests
        self.request_history[user_id][endpoint] = [
            ts for ts in self.request_history[user_id][endpoint] if ts > cutoff
        ]

        limit = self.endpoint_limits.get(endpoint, self.default_rps_per_minute)
        if len(self.request_history[user_id][endpoint]) >= limit:
            return True

        # Record this request
        self.request_history[user_id][endpoint].append(now)
        return False


# ============================================================================
# IDEMPOTENCY TRACKING
# ============================================================================

class IdempotencyManager:
    """Manages idempotent request handling to prevent duplicate operations."""

    def __init__(self):
        # {idempotency_key: (user_id, endpoint, response_hash, timestamp)}
        self.requests: Dict[str, Dict[str, Any]] = {}

    def get_cached_response(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached response for idempotency key if within window."""
        if idempotency_key not in self.requests:
            return None

        entry = self.requests[idempotency_key]
        # Idempotency key valid for 24 hours
        if datetime.utcnow() - entry["timestamp"] > timedelta(hours=24):
            del self.requests[idempotency_key]
            return None

        return entry.get("response")

    def cache_response(
        self, idempotency_key: str, user_id: str, endpoint: str, response: Dict[str, Any]
    ):
        """Cache response for idempotency key."""
        self.requests[idempotency_key] = {
            "user_id": user_id,
            "endpoint": endpoint,
            "response": response,
            "timestamp": datetime.utcnow(),
            "response_hash": hashlib.sha256(
                str(response).encode()
            ).hexdigest(),
        }


# ============================================================================
# REQUEST SIGNING
# ============================================================================

class RequestSigner:
    """Signs and verifies requests for integrity and non-repudiation."""

    def __init__(self, secret_key: Optional[str] = None):
        self.secret_key = secret_key or os.getenv(
            "REQUEST_SIGNING_KEY", "dev-signing-key-change-in-production"
        )

    def sign_request(
        self, method: str, path: str, body: str, timestamp: str
    ) -> str:
        """Generate HMAC-SHA256 signature for request."""
        message = f"{method}|{path}|{body}|{timestamp}"
        signature = hmac.new(
            self.secret_key.encode(), message.encode(), hashlib.sha256
        ).hexdigest()
        return signature

    def verify_signature(
        self,
        method: str,
        path: str,
        body: str,
        timestamp: str,
        signature: str,
    ) -> bool:
        """Verify request signature."""
        expected_sig = self.sign_request(method, path, body, timestamp)
        return hmac.compare_digest(signature, expected_sig)


# ============================================================================
# DEPENDENCIES FOR FASTAPI
# ============================================================================

# Global instances
jwt_manager = JWTTokenManager()
rate_limiter = RateLimiter()
idempotency_manager = IdempotencyManager()
request_signer = RequestSigner()

security = HTTPBearer()


async def get_current_user(credentials: HTTPAuthCredentials = Depends(security)) -> tuple[
    str, UserRole
]:
    """FastAPI dependency to extract and validate JWT token."""
    token = credentials.credentials
    user_id, role = jwt_manager.get_user_from_token(token)
    return user_id, role


async def check_permission(permission: PermissionType) -> Callable:
    """Factory for creating permission-checking dependencies."""

    async def _check_permission(
        current_user: tuple[str, UserRole] = Depends(get_current_user),
    ) -> tuple[str, UserRole]:
        user_id, role = current_user
        if permission not in ROLE_PERMISSIONS.get(role, []):
            raise HTTPException(
                status_code=403,
                detail=f"User {user_id} ({role.value}) lacks permission: {permission.value}",
            )
        return user_id, role

    return _check_permission


async def check_rate_limit(request: Request) -> str:
    """Validate rate limit for current user/endpoint."""
    # Extract user from token (must already be authenticated)
    try:
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "")
        user_id, _ = jwt_manager.get_user_from_token(token)
    except:
        user_id = request.client.host  # Fallback to IP

    endpoint = request.url.path
    if rate_limiter.is_rate_limited(user_id, endpoint):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Max requests per minute exceeded.",
        )
    return user_id


async def handle_idempotency(request: Request) -> Optional[Dict[str, Any]]:
    """Check for idempotency key and return cached response if available."""
    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key:
        return None

    cached_response = idempotency_manager.get_cached_response(idempotency_key)
    if cached_response:
        return cached_response
    return None


# ============================================================================
# DECORATORS
# ============================================================================


def require_permission(permission: PermissionType):
    """Decorator to enforce permission checks on endpoints."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            user_id, role = kwargs.get("current_user", (None, None))
            if not user_id:
                raise HTTPException(status_code=401, detail="Not authenticated")

            if permission not in ROLE_PERMISSIONS.get(role, []):
                raise HTTPException(status_code=403, detail="Permission denied")

            return await func(*args, **kwargs)

        return wrapper

    return decorator


def require_rate_limit:
    """Decorator for rate limit checking."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, request: Request, **kwargs):
            user_id = await check_rate_limit(request)
            return await func(*args, **kwargs)

        return wrapper

    return decorator


# ============================================================================
# AUDIT LOGGING
# ============================================================================

class AuditLogger:
    """Logs sensitive operations for compliance and audit trails."""

    def __init__(self, log_file: str = "audit.log"):
        self.log_file = log_file

    def log_operation(
        self,
        user_id: str,
        operation: str,
        resource: str,
        action: str,
        status: str,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Log an operation to audit trail."""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "user_id": user_id,
            "operation": operation,
            "resource": resource,
            "action": action,
            "status": status,
            "details": details or {},
        }

        with open(self.log_file, "a") as f:
            import json

            f.write(json.dumps(entry) + "\n")

    def log_trade_execution(
        self,
        user_id: str,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        status: str,
    ):
        """Log trade execution."""
        self.log_operation(
            user_id=user_id,
            operation="TRADE_EXECUTION",
            resource=ticker,
            action=f"{side} {quantity}",
            status=status,
            details={"side": side, "quantity": quantity, "price": price},
        )

    def log_config_change(
        self, user_id: str, config_key: str, old_value: Any, new_value: Any
    ):
        """Log configuration changes."""
        self.log_operation(
            user_id=user_id,
            operation="CONFIG_CHANGE",
            resource=config_key,
            action="UPDATE",
            status="SUCCESS",
            details={"old_value": str(old_value), "new_value": str(new_value)},
        )

    def log_failed_auth(self, user_id: str, reason: str):
        """Log failed authentication attempts."""
        self.log_operation(
            user_id=user_id,
            operation="AUTH_FAILURE",
            resource="system",
            action="LOGIN",
            status="FAILED",
            details={"reason": reason},
        )


audit_logger = AuditLogger(log_file="logs/audit.log")
