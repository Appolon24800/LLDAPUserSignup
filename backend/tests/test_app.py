"""App factory behaviour: health endpoint and JSON error shaping."""

from __future__ import annotations


def test_healthz_ok(client):
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.get_json() == {"status": "ok"}


def test_unknown_route_returns_json_404(client):
    res = client.get("/api/v1/nope")
    assert res.status_code == 404
    body = res.get_json()
    assert body["error"]["code"] == "not_found"


def test_method_not_allowed_returns_json(client):
    res = client.post("/healthz")
    assert res.status_code == 405
    assert res.get_json()["error"]["code"] == "not_found"


def test_max_content_length_set(app, config):
    assert app.config["MAX_CONTENT_LENGTH"] == config.max_upload_mb * 1024 * 1024


def test_creates_database_file(tmp_path):
    from app import create_app
    from tests.conftest import make_config

    cfg = make_config(tmp_path, database_path=str(tmp_path / "nested" / "dir" / "x.db"))
    create_app(cfg)
    assert (tmp_path / "nested" / "dir" / "x.db").exists()
