"""Integration tests for terminal routes (mTLS + session token)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


@pytest.fixture
def app_client():
    import app as flask_app

    flask_app.app.config["TESTING"] = True
    return flask_app.app.test_client()


@pytest.fixture
def session_token(app_client):
    """Acquire a session token (simulates mTLS-authenticated request)."""
    import app as flask_app

    resp = app_client.post("/terminal/session-token")
    assert resp.status_code == 200
    return resp.get_json()["token"]


class TestTerminalRoutes:
    def test_terminal_page_returns_html(self, app_client):
        resp = app_client.get("/terminal")
        assert resp.status_code == 200

    def test_session_token_endpoint(self, app_client):
        resp = app_client.post("/terminal/session-token")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "token" in data
        assert len(data["token"]) == 64

    def test_sessions_requires_auth(self, app_client):
        resp = app_client.get("/terminal/sessions")
        assert resp.status_code == 401

    def test_sessions_with_valid_token(self, app_client, session_token):
        resp = app_client.get(
            "/terminal/sessions",
            headers={"Authorization": f"Bearer {session_token}"},
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
