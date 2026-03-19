"""Integration tests for terminal routes."""

import os
import sys

import pytest

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from terminal_auth import generate_token


@pytest.fixture
def token_path(tmp_path):
    path = str(tmp_path / "token")
    generate_token(path)
    return path


@pytest.fixture
def app_client(token_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "TERMINAL_TOKEN_PATH", token_path)

    import app as flask_app

    flask_app.app.config["TESTING"] = True
    return flask_app.app.test_client()


class TestTerminalRoutes:
    def test_terminal_page_returns_html(self, app_client):
        resp = app_client.get("/terminal")
        assert resp.status_code == 200

    def test_sessions_requires_auth(self, app_client):
        resp = app_client.get("/terminal/sessions")
        assert resp.status_code == 401

    def test_sessions_with_valid_token(self, app_client, token_path):
        with open(token_path) as f:
            token = f.read().strip()
        resp = app_client.get(
            "/terminal/sessions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "sessions" in data

    def test_sessions_with_invalid_token(self, app_client):
        resp = app_client.get(
            "/terminal/sessions",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401
