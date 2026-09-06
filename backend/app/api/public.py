"""Public registration API.

POST /api/v1/validate-code  {code}               -> validity + expiry
POST /api/v1/register       multipart form       -> create the LLDAP user

Every failed code attempt feeds the shared IP lockout; every failed
submission with a valid code also counts toward the code's own
max-failed-attempts limit (see app.codes / app.lockout).
"""

from __future__ import annotations

import unicodedata

from flask import Blueprint, current_app, jsonify, request

from ..codes import CodeClaimError
from ..errors import ApiError, ErrorCode
from ..images import ImageRejected, process_photo
from ..ldap_service import LdapServiceError, UserAlreadyExistsError
from ..limiter import limiter
from ..notifier import notify_account_created
from ..validation import (
    split_full_name,
    validate_email,
    validate_name,
    validate_password,
    validate_username,
)

blp = Blueprint("public", __name__, url_prefix="/api/v1")

_CODE_STATUS_TO_ERROR = {
    "invalid": (ErrorCode.INVALID_CODE, "Unknown registration code"),
    "expired": (ErrorCode.CODE_EXPIRED, "This registration code has expired"),
    "used": (ErrorCode.CODE_USED, "This registration code has already been used"),
    "revoked": (ErrorCode.CODE_REVOKED, "This registration code was revoked"),
    "locked": (ErrorCode.CODE_LOCKED, "This registration code is locked"),
}


def _store():
    return current_app.extensions["code_store"]


def _lockout():
    return current_app.extensions["ip_lockout"]


def _ldap():
    return current_app.extensions["ldap_service"]


def _cfg():
    return current_app.config["APP_CONFIG"]


def _check_ip_lockout() -> None:
    lockout = _lockout()
    ip = request.remote_addr or "unknown"
    remaining = lockout.locked_for(ip)
    if remaining > 0:
        raise ApiError(
            ErrorCode.IP_LOCKED,
            "Too many failed attempts; please wait before trying again",
            429,
            headers={"Retry-After": str(int(remaining) + 1)},
        )


def _register_ip_failure() -> None:
    _lockout().register_failure(request.remote_addr or "unknown")


def _code_error(status: str) -> ApiError:
    code, message = _CODE_STATUS_TO_ERROR.get(
        status, (ErrorCode.INVALID_CODE, "Unknown registration code")
    )
    return ApiError(code, message, 400)


@blp.post("/validate-code")
@limiter.limit(lambda: current_app.config["APP_CONFIG"].rate_limit_validate)
def validate_code():
    body = request.get_json(silent=True) or {}
    code = body.get("code")
    if not isinstance(code, str) or not 1 <= len(code.strip()) <= 200:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "A registration code is required",
            400,
            field_errors={"code": "required"},
        )
    code = code.strip()

    _check_ip_lockout()
    status = _store().status(code)
    if status != "valid":
        _register_ip_failure()
        raise _code_error(status)

    _lockout().reset(request.remote_addr or "unknown")
    record = _store().get(code)
    return jsonify(
        {
            "valid": True,
            "expires_at": record.expires_at.isoformat(),
            "platform_name": _cfg().platform_name,
        }
    )


@blp.post("/register")
@limiter.limit(lambda: current_app.config["APP_CONFIG"].rate_limit_submit)
def register():
    cfg = _cfg()
    _check_ip_lockout()

    form = request.form
    code = (form.get("code") or "").strip()
    username = unicodedata.normalize("NFC", form.get("username") or "")
    full_name = unicodedata.normalize("NFC", (form.get("full_name") or "").strip())
    email = unicodedata.normalize("NFC", (form.get("email") or "").strip())
    password = form.get("password") or ""

    status = _store().status(code)
    if status != "valid":
        _register_ip_failure()
        raise _code_error(status)

    # A failure from here on means the code itself was valid, so each one
    # counts toward the code's own failed-attempt limit as well as the
    # caller's IP lockout.
    def _fail(err: ApiError, count_code_row: bool = True) -> ApiError:
        if count_code_row:
            _store().register_failure(code)
        _register_ip_failure()
        return err

    field_errors: dict[str, str] = {}
    for field, value, validator in (
        ("username", username, validate_username),
        ("full_name", full_name, validate_name),
        ("email", email, validate_email),
        ("password", password, validate_password),
    ):
        error = validator(value)
        if error:
            field_errors[field] = error
    if not username:
        field_errors.setdefault("username", "required")

    photo_jpeg: bytes | None = None
    upload = request.files.get("photo")
    if upload is not None and upload.filename:
        data = upload.read()
        max_bytes = cfg.max_upload_mb * 1024 * 1024
        try:
            photo_jpeg = process_photo(data, max_bytes)
        except ImageRejected as err:
            field_errors["photo"] = err.code

    if field_errors:
        raise _fail(
            ApiError(
                ErrorCode.VALIDATION_ERROR,
                "Some fields need attention",
                400,
                field_errors=field_errors,
            )
        )

    if _ldap().user_exists(username):
        raise _fail(
            ApiError(
                ErrorCode.USERNAME_TAKEN,
                "This username is already taken",
                409,
                field_errors={"username": "taken"},
            )
        )

    try:
        record = _store().claim(code, username)
    except CodeClaimError as err:
        _register_ip_failure()
        raise _code_error(err.status) from err

    # Rollback rules: always return the code on server-side failures, but
    # only delete the LDAP entry when we know we created it (group-add
    # failure). On UserAlreadyExistsError the entry belongs to someone else
    # and must not be touched.
    try:
        first_name, last_name = split_full_name(full_name)
        _ldap().create_user(
            username=username,
            password=password,
            first_name=first_name,
            last_name=last_name,
            display_name=full_name,
            email=email,
            photo_jpeg=photo_jpeg,
        )
    except UserAlreadyExistsError:
        _store().revert_claim(code, username)
        raise ApiError(
            ErrorCode.USERNAME_TAKEN,
            "This username is already taken",
            409,
            field_errors={"username": "taken"},
        ) from None
    except LdapServiceError as err:
        _store().revert_claim(code, username)
        current_app.logger.error("user creation failed during registration: %s", err)
        raise ApiError(
            ErrorCode.LDAP_ERROR,
            "The directory is unavailable; please try again later",
            502,
        ) from err

    try:
        _ldap().add_to_groups(username, list(record.groups))
    except LdapServiceError as err:
        _store().revert_claim(code, username)
        _cleanup_user(username)
        current_app.logger.error("group membership failed during registration: %s", err)
        raise ApiError(
            ErrorCode.LDAP_ERROR,
            "The directory is unavailable; please try again later",
            502,
        ) from err

    _lockout().reset(request.remote_addr or "unknown")
    notify_account_created(_cfg(), display_name=full_name)
    return jsonify({"username": username, "created": True}), 201


def _cleanup_user(username: str) -> None:
    """Best-effort removal of a user created during a failed registration."""
    try:
        _ldap().delete_user(username)
    except Exception:  # rollback must never mask the original error
        current_app.logger.exception("Rollback failed for user %s", username)
