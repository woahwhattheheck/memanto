from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from memanto.app.services import session_service as session_module
from memanto.app.services.session_service import SessionService


def test_private_json_replace_syncs_parent_before_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    service = SessionService(secret_key="fixed", sessions_dir=sessions_dir)
    target = sessions_dir / "agent.json"
    events: list[tuple[str, Path]] = []
    real_replace = session_module.os.replace

    def recording_replace(
        source: str | os.PathLike[str], destination: str | os.PathLike[str]
    ) -> None:
        real_replace(source, destination)
        events.append(("replace", Path(destination)))

    def recording_dirsync(path: Path) -> None:
        events.append(("dirsync", path))

    monkeypatch.setattr(session_module.os, "replace", recording_replace)
    monkeypatch.setattr(service, "_fsync_directory", recording_dirsync)

    service._write_private_json_atomic(target, {"session": "durable"})

    assert json.loads(target.read_text(encoding="utf-8")) == {"session": "durable"}
    assert events == [("replace", target), ("dirsync", sessions_dir)]


def test_private_json_failed_replace_does_not_dirsync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    service = SessionService(secret_key="fixed", sessions_dir=sessions_dir)
    target = sessions_dir / "agent.json"
    dirsync_calls: list[Path] = []

    def failing_replace(
        source: str | os.PathLike[str], destination: str | os.PathLike[str]
    ) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(session_module.os, "replace", failing_replace)
    monkeypatch.setattr(
        service, "_fsync_directory", lambda path: dirsync_calls.append(path)
    )

    with pytest.raises(OSError, match="replace failed"):
        service._write_private_json_atomic(target, {"session": "not committed"})

    assert dirsync_calls == []
    assert not target.exists()
    assert list(sessions_dir.glob(".agent.json.*.tmp")) == []


def test_generated_secret_syncs_parent_after_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = SessionService(sessions_dir=tmp_path / "sessions")
    secret_file = tmp_path / "secret_key"
    events: list[tuple[str, Path]] = []
    real_replace = session_module.os.replace

    def recording_replace(
        source: str | os.PathLike[str], destination: str | os.PathLike[str]
    ) -> None:
        real_replace(source, destination)
        events.append(("replace", Path(destination)))

    def recording_dirsync(path: Path) -> None:
        events.append(("dirsync", path))

    monkeypatch.setattr(session_module.os, "replace", recording_replace)
    monkeypatch.setattr(service, "_fsync_directory", recording_dirsync)

    secret = service._generate_secure_secret_key()

    assert secret_file.read_text(encoding="utf-8") == secret
    assert events == [("replace", secret_file), ("dirsync", tmp_path)]


@pytest.mark.skipif(os.name == "nt", reason="directory fsync is POSIX-only")
def test_fsync_directory_flushes_and_closes_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, object]] = []
    fake_fd = 73

    def fake_open(path: str | os.PathLike[str], flags: int) -> int:
        calls.append(("open", (Path(path), flags)))
        return fake_fd

    def fake_fsync(fd: int) -> None:
        calls.append(("fsync", fd))

    def fake_close(fd: int) -> None:
        calls.append(("close", fd))

    monkeypatch.setattr(session_module.os, "open", fake_open)
    monkeypatch.setattr(session_module.os, "fsync", fake_fsync)
    monkeypatch.setattr(session_module.os, "close", fake_close)

    SessionService._fsync_directory(tmp_path)

    expected_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    assert calls[0] == ("open", (tmp_path, expected_flags))
    assert calls[1:] == [("fsync", fake_fd), ("close", fake_fd)]
