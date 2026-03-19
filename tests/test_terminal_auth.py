"""Tests for terminal token authentication."""

import os

import pytest

from terminal_auth import generate_token, load_token, validate_token


class TestTokenGeneration:
    def test_generate_token_creates_file(self, tmp_path):
        token_path = str(tmp_path / "token")
        token = generate_token(token_path)
        assert os.path.isfile(token_path)
        assert len(token) == 64  # 32 bytes hex

    def test_generate_token_file_permissions(self, tmp_path):
        token_path = str(tmp_path / "token")
        generate_token(token_path)
        mode = oct(os.stat(token_path).st_mode & 0o777)
        assert mode == "0o600"

    def test_generate_token_does_not_overwrite(self, tmp_path):
        token_path = str(tmp_path / "token")
        token1 = generate_token(token_path)
        token2 = generate_token(token_path)
        assert token1 == token2


class TestTokenValidation:
    def test_load_token_reads_file(self, tmp_path):
        token_path = str(tmp_path / "token")
        generated = generate_token(token_path)
        loaded = load_token(token_path)
        assert loaded == generated

    def test_load_token_missing_file(self, tmp_path):
        loaded = load_token(str(tmp_path / "nonexistent"))
        assert loaded is None

    def test_validate_token_correct(self, tmp_path):
        token_path = str(tmp_path / "token")
        token = generate_token(token_path)
        assert validate_token(token, token_path) is True

    def test_validate_token_wrong(self, tmp_path):
        token_path = str(tmp_path / "token")
        generate_token(token_path)
        assert validate_token("wrong-token", token_path) is False

    def test_validate_token_empty(self, tmp_path):
        token_path = str(tmp_path / "token")
        generate_token(token_path)
        assert validate_token("", token_path) is False
