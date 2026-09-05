"""Internal API for the Telegram bot.

Authenticated with a shared secret (X-Internal-API-Key, constant-time
compared). Only these endpoints ever return a raw code token — the bot
delivers it to the admin over Telegram. Generous fixed rate limits; the
allow-listed bot is the only expected caller.
"""

from __future__ import annotations

import hmac
import re
from functools import wraps

from flask import Blueprint, current_app, jsonify, request

from ..errors import ApiError, ErrorCode
from ..ldap_service import LdapServiceError
from ..limiter import limiter

blp = Blueprint("internal", __name__, url_prefix="/internal")

GROUP_NAME_RE = re.compile(r"^[\w][\w .\-']{0,63}$", re.UNICODE)


def internal_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        provided = request.headers.get("X-Internal-API-Key", "")
        expected = current_app.config["APP_CONFIG"].internal_api_key
        if not provided or not hmac.compare_digest(provided, expected):
            raise ApiError(ErrorCode.UNAUTHORIZED, "Not authorized", 401)
        return fn(*args, **kwargs)

    return wrapper


def _store():
    return current_app.extensions["code_store"]


def _ldap():
    return current_app.extensions["ldap_service"]


def _require_json() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError(ErrorCode.VALIDATION_ERROR, "A JSON object body is required", 400)
    return body


@blp.post("/codes")
@limiter.limit("60 per minute")
@internal_auth
def create_code():
    """Generate a single-use code scoped to the given LLDAP groups."""
    body = _require_json()
    groups = body.get("groups")
    created_by = str(body.get("created_by", "")).strip()

    if not isinstance(groups, list) or not groups:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "groups must be a non-empty list",
            400,
            field_errors={"groups": "required"},
        )
    if len(groups) > 20:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "too many groups",
            400,
            field_errors={"groups": "too_many"},
        )
    if not 1 <= len(created_by) <= 64:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "created_by is required",
            400,
            field_errors={"created_by": "required"},
        )
    seen: set[str] = set()
    for group in groups:
        if not isinstance(group, str) or not GROUP_NAME_RE.fullmatch(group):
            raise ApiError(
                ErrorCode.VALIDATION_ERROR,
                "invalid group name",
                400,
                field_errors={"groups": "invalid_format"},
            )
        seen.add(group)
    groups = sorted(seen)

    # The groups must exist in LLDAP right now: the account would otherwise
    # be created but left out of its intended groups.
    try:
        available = set(_ldap().list_groups())
    except LdapServiceError:
        raise ApiError(ErrorCode.LDAP_ERROR, "The directory is unavailable", 502) from None
    unknown = [g for g in groups if g not in available]
    if unknown:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "unknown groups: " + ", ".join(unknown),
            400,
            field_errors={"groups": "unknown"},
        )

    cfg = current_app.config["APP_CONFIG"]
    token = _store().create(groups, created_by=created_by)
    record = _store().get(token)
    return (
        jsonify(
            {
                "code": token,
                "url": f"{cfg.base_url}/register?code={token}",
                "groups": list(record.groups),
                "expires_at": record.expires_at.isoformat(),
            }
        ),
        201,
    )


@blp.get("/codes")
@limiter.limit("60 per minute")
@internal_auth
def list_codes():
    """Active (unused, unrevoked, unexpired) codes, newest first."""
    records = _store().list_active()
    return jsonify(
        {
            "codes": [
                {
                    "code_hint": r.code_hint,
                    "groups": list(r.groups),
                    "created_by": r.created_by,
                    "created_at": r.created_at.isoformat(),
                    "expires_at": r.expires_at.isoformat(),
                    "failed_attempts": r.failed_attempts,
                }
                for r in records
            ]
        }
    )


@blp.post("/revoke")
@limiter.limit("60 per minute")
@internal_auth
def revoke_code():
    body = _require_json()
    code = body.get("code")
    if not isinstance(code, str) or not 1 <= len(code.strip()) <= 200:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "code is required",
            400,
            field_errors={"code": "required"},
        )
    revoked = _store().revoke(code.strip())
    return jsonify({"revoked": revoked})


@blp.get("/groups")
@limiter.limit("60 per minute")
@internal_auth
def list_groups():
    try:
        return jsonify({"groups": _ldap().list_groups()})
    except LdapServiceError:
        raise ApiError(ErrorCode.LDAP_ERROR, "The directory is unavailable", 502) from None
