"""Tests for session token authentication."""

import time

import pytest

from terminal_auth import SessionTokenStore


class TestSessionTokenStore:
    def test_issue_returns_64_char_hex(self):
        store = SessionTokenStore(ttl=60)
        token = store.issue()
        assert len(token) == 64
        assert all(c in "0123456789abcdef" for c in token)

    def test_validate_issued_token(self):
        store = SessionTokenStore(ttl=60)
        token = store.issue()
        assert store.validate(token) is True

    def test_validate_wrong_token(self):
        store = SessionTokenStore(ttl=60)
        store.issue()
        assert store.validate("wrong-token") is False

    def test_validate_empty_token(self):
        store = SessionTokenStore(ttl=60)
        assert store.validate("") is False

    def test_expired_token_rejected(self):
        store = SessionTokenStore(ttl=0)  # expires immediately
        token = store.issue()
        time.sleep(0.01)
        assert store.validate(token) is False

    def test_revoke_token(self):
        store = SessionTokenStore(ttl=60)
        token = store.issue()
        store.revoke(token)
        assert store.validate(token) is False

    def test_revoke_all(self):
        store = SessionTokenStore(ttl=60)
        t1 = store.issue()
        t2 = store.issue()
        store.revoke_all()
        assert store.validate(t1) is False
        assert store.validate(t2) is False

    def test_active_count(self):
        store = SessionTokenStore(ttl=60)
        assert store.active_count == 0
        store.issue()
        store.issue()
        assert store.active_count == 2

    def test_multiple_tokens_independent(self):
        store = SessionTokenStore(ttl=60)
        t1 = store.issue()
        t2 = store.issue()
        assert store.validate(t1) is True
        assert store.validate(t2) is True
        store.revoke(t1)
        assert store.validate(t1) is False
        assert store.validate(t2) is True
