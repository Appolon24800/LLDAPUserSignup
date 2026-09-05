"""Flask application factory."""

from __future__ import annotations

from flask import Flask, request
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from .codes import CodeStore
from .config import Config
from .db import init_db
from .errors import ApiError, ErrorCode, error_response
from .ldap_service import LdapService
from .limiter import limiter
from .lockout import IpLockout


def create_app(config: Config | None = None) -> Flask:
    cfg = config if config is not None else Config.from_env()

    app = Flask(__name__)
    app.config.update(
        APP_CONFIG=cfg,
        SECRET_KEY=cfg.flask_secret_key,
        MAX_CONTENT_LENGTH=cfg.max_upload_mb * 1024 * 1024,
    )
    app.json.sort_keys = False

    limiter.init_app(app)
    app.extensions["code_store"] = CodeStore(
        cfg.database_path, cfg.max_failed_attempts, cfg.code_expiry_minutes
    )
    app.extensions["ip_lockout"] = IpLockout(cfg.database_path)
    app.extensions["ldap_service"] = LdapService(
        url=cfg.ldap_url,
        admin_dn=cfg.ldap_admin_dn,
        admin_password=cfg.ldap_admin_password,
        base_dn=cfg.ldap_base_dn,
        allow_insecure=cfg.ldap_allow_insecure,
    )

    if cfg.cors_allowed_origins:
        from flask_cors import CORS

        CORS(app, resources={r"/api/v1/*": {"origins": list(cfg.cors_allowed_origins)}})

    # Trust exactly N proxies in front of us so rate limits key on the real
    # client IP. PROXY_TRUSTED_COUNT must match the deployment topology
    # (default 1: the bundled nginx proxy).
    app.wsgi_app = ProxyFix(  # type: ignore[method-assign]
        app.wsgi_app,
        x_for=cfg.proxy_trusted_count,
        x_proto=1 if cfg.proxy_trusted_count else 0,
        x_host=1 if cfg.proxy_trusted_count else 0,
    )

    init_db(cfg.database_path)

    from .api.health import blp as health_blp
    from .api.internal import blp as internal_blp
    from .api.public import blp as public_blp

    app.register_blueprint(health_blp)
    app.register_blueprint(public_blp)
    app.register_blueprint(internal_blp)

    _register_error_handlers(app)
    return app


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.code, err.message, err.status, err.field_errors, err.headers)

    @app.errorhandler(HTTPException)
    def handle_http_exception(err: HTTPException):
        code_by_status = {
            401: ErrorCode.UNAUTHORIZED,
            404: ErrorCode.NOT_FOUND,
            405: ErrorCode.NOT_FOUND,
            413: ErrorCode.PAYLOAD_TOO_LARGE,
            415: ErrorCode.UNSUPPORTED_MEDIA_TYPE,
            429: ErrorCode.RATE_LIMITED,
        }
        fallback = (
            ErrorCode.INTERNAL_ERROR
            if err.code >= 500
            else err.name.lower().replace(" ", "_")
        )
        code = code_by_status.get(err.code, fallback)
        status = err.code or 500
        # Never leak internal detail for server errors.
        message = err.description if status < 500 else "Internal server error"
        headers = {}
        if status == 429:
            retry_after = getattr(err, "retry_after", None)
            headers["Retry-After"] = str(retry_after) if retry_after else "60"
        return error_response(code, message, status, headers=headers or None)

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        app.logger.exception("Unhandled error on %s %s", request.method, request.path)
        return error_response(ErrorCode.INTERNAL_ERROR, "Internal server error", 500)
