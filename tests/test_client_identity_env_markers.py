from __future__ import annotations

import memanto.app.utils.client_identity as client_identity


def _clear_identity_environment(monkeypatch) -> None:
    monkeypatch.delenv("MEMANTO_CLIENT", raising=False)
    for env_names, _tool, _display in client_identity._ENV_SIGNATURES:
        for name in env_names:
            monkeypatch.delenv(name, raising=False)


def test_empty_and_whitespace_markers_do_not_identify_client(monkeypatch) -> None:
    _clear_identity_environment(monkeypatch)
    monkeypatch.setenv("CURSOR_TRACE_ID", "")
    monkeypatch.setenv("CURSOR_AGENT", "   \t")

    detected = client_identity.detect_client()

    assert detected.tool == client_identity.UNKNOWN_TOOL
    assert detected.display == "Unknown client"


def test_empty_higher_priority_marker_does_not_mask_nonempty_marker(
    monkeypatch,
) -> None:
    _clear_identity_environment(monkeypatch)
    monkeypatch.setenv("CURSOR_TRACE_ID", "")
    monkeypatch.setenv("CLAUDECODE", "1")

    detected = client_identity.detect_client()

    assert detected.tool == "claude-code"
    assert detected.display == "Claude Code"


def test_nonempty_marker_still_identifies_client(monkeypatch) -> None:
    _clear_identity_environment(monkeypatch)
    monkeypatch.setenv("CODEX_SANDBOX", "sandboxed")

    detected = client_identity.detect_client()

    assert detected.tool == "codex"
    assert detected.display == "Codex CLI"
