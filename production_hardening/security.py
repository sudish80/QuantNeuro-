"""Security helpers: secret management and optional encrypted logging."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from production_hardening.io_utils import append_bytes_locked


def load_secret(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise ValueError(f"Missing required secret: {name}")
    return value


def mask_secret(value: str, keep: int = 4) -> str:
    if len(value) <= keep * 2:
        return "*" * len(value)
    return value[:keep] + "*" * (len(value) - 2 * keep) + value[-keep:]


def hmac_sha256_hex(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    # PBKDF2-HMAC-SHA256 derives a 256-bit key suitable for AES-256-GCM.
    return hashlib.pbkdf2_hmac(
        "sha256",
        passphrase.encode("utf-8"),
        salt,
        200_000,
        dklen=32,
    )


def encrypt_bytes(data: bytes, passphrase: str) -> bytes:
    """Encrypt bytes with AES-256-GCM using PBKDF2-derived key material."""
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _derive_key(passphrase, salt)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, data, None)
    payload = salt + nonce + ciphertext
    return base64.b64encode(payload)


def decrypt_bytes(data: bytes, passphrase: str) -> bytes:
    raw = base64.b64decode(data)
    if len(raw) < 29:
        raise ValueError("Encrypted payload is too short")
    salt = raw[:16]
    nonce = raw[16:28]
    ciphertext = raw[28:]
    key = _derive_key(passphrase, salt)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


def append_encrypted_line(file_path: str, line: str, passphrase: str) -> None:
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encrypted = encrypt_bytes((line + "\n").encode("utf-8"), passphrase)
    append_bytes_locked(path, encrypted + b"\n")


def append_kms_encrypted_line(
    file_path: str,
    line: str,
    kms_key_id: str,
    kms_region: str,
    encryption_context: dict[str, str] | None = None,
) -> None:
    """Encrypt a log line with managed AWS KMS and append ciphertext to file."""
    try:
        import boto3  # type: ignore
        from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError  # type: ignore
    except Exception as ex:  # pragma: no cover
        raise RuntimeError("boto3 is required for KMS-backed encryption") from ex

    if not kms_key_id:
        raise ValueError("kms_key_id is required for KMS-backed encryption")

    try:
        kms = boto3.client("kms", region_name=kms_region)
        ctx = encryption_context or {}
        response: dict[str, Any] = kms.encrypt(
            KeyId=kms_key_id,
            Plaintext=(line + "\n").encode("utf-8"),
            EncryptionContext=ctx,
        )
        ciphertext = response["CiphertextBlob"]
        encoded = base64.b64encode(ciphertext)
    except (NoCredentialsError, ClientError, BotoCoreError) as ex:
        raise RuntimeError(f"KMS encryption failed: {ex}") from ex
    except KeyError as ex:
        raise RuntimeError("KMS encryption response missing CiphertextBlob") from ex

    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    append_bytes_locked(path, encoded + b"\n")
