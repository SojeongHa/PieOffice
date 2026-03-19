"""Tests for terminal session management."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from terminal import (
    TmuxSession,
    list_tmux_sessions,
    parse_tmux_list,
)


class TestParseTmuxList:
    def test_parse_single_session(self):
        raw = "claude-abc123:1:0:/Users/temple/workspace/mcp-giboo"
        sessions = parse_tmux_list(raw)
        assert len(sessions) == 1
        assert sessions[0].name == "claude-abc123"
        assert sessions[0].windows == 1
        assert sessions[0].attached == 0
        assert sessions[0].cwd == "/Users/temple/workspace/mcp-giboo"

    def test_parse_multiple_sessions(self):
        raw = (
            "claude-abc:2:1:/Users/temple/a\n"
            "claude-def:1:0:/Users/temple/b"
        )
        sessions = parse_tmux_list(raw)
        assert len(sessions) == 2

    def test_parse_empty(self):
        assert parse_tmux_list("") == []
        assert parse_tmux_list("\n") == []

    def test_parse_attached_session(self):
        raw = "claude-abc:1:1:/Users/temple/a"
        sessions = parse_tmux_list(raw)
        assert sessions[0].attached == 1


class TestListTmuxSessions:
    @patch("terminal.subprocess.run")
    def test_list_filters_claude_sessions(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="claude-abc:1:0:/tmp\nother-session:1:0:/tmp\nclaude-def:1:0:/tmp",
        )
        sessions = list_tmux_sessions()
        assert len(sessions) == 2
        assert all(s.name.startswith("claude-") for s in sessions)

    @patch("terminal.subprocess.run")
    def test_list_empty_when_no_tmux(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        sessions = list_tmux_sessions()
        assert sessions == []
