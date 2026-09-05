"""Stable, machine-readable error codes and JSON error shaping.

The frontend maps these codes to translated messages, so error responses stay
translatable without any locale negotiation on the server.
"""

from __future__ import annotations

from typing import Any

from flask import jsonify


class ErrorCode:
    """Namespace of stable error code strings returned to clients."""

    INVALID_CODE = "invalid_code"
    CODE_EXPIRED = "code_expired"
    CODE_USED = "code_used"
    CODE_REVOKED = "code_revoked"
    CODE_LOCKED = "code_locked"
    IP_LOCKED = "ip_locked"
    USERNAME_TAKEN = "username_taken"
    VALIDATION_ERROR = "validation_error"
    UNAUTHORIZED = "unauthorized"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    UNSUPPORTED_IMAGE = "unsupported_image"
    RATE_LIMITED = "rate_limited"
    LDAP_ERROR = "ldap_error"
    NOT_FOUND = "not_found"
    INTERNAL_ERROR = "internal_error"


class ApiError(Exception):
    """Raise anywhere in a request to return a structured JSON error."""

    def __init__(
        self,
        code: str,
        message: str,
        status: int = 400,
        field_errors: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.field_errors = field_errors
        self.headers = headers


def error_response(
    code: str,
    message: str,
    status: int = 400,
    field_errors: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[Any, int] | tuple[Any, int, dict[str, str]]:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if field_errors:
        body["error"]["field_errors"] = field_errors
    if headers:
        return jsonify(body), status, headers
    return jsonify(body), status
