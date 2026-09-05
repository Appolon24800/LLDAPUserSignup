"""Liveness endpoint used by container healthchecks and CI."""

from __future__ import annotations

from flask import Blueprint, jsonify

blp = Blueprint("health", __name__)


@blp.get("/healthz")
def healthz():
    return jsonify({"status": "ok"})
