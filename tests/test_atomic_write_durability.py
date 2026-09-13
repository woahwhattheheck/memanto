from __future__ import annotations

import os
from pathlib import Path

import pytest

from memanto.app.utils import atomic_write as atomic_write_module
from memanto.app.utils.atomic_write import atomic_write_text


def test_atomic_write_syncs_parent_after_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "state.json"
    events: list[tuple[str, Path]] = []
    real_replace = atomic_write_module.os.replace

    def recording_replace(
        source: str | os.PathLike[str], destination: str | os.PathLike[str]
    ) -> None:
        real_replace(source, destination)
        events.append(("replace", Path(destination)))

    def recording_dirsync(path: Path) -> None:
        events.append(("dirsync", path))

    monkeypatch.setattr(atomic_write_module.os, "replace", recording_replace)
    monkeypatch.setattr(atomic_write_module, "_fsync_directory", recording_dirsync)

    atomic_write_text(target, "durable")

    assert target.read_text(encoding="utf-8") == "durable"
    assert events == [("replace", target), ("dirsync", tmp_path)]


def test_atomic_write_syncs_created_parent_chain_inside_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "outer" / "inner" / "state.json"
    events: list[tuple[str, Path]] = []
    real_replace = atomic_write_module.os.replace

    def recording_replace(
        source: str | os.PathLike[str], destination: str | os.PathLike[str]
    ) -> None:
        real_replace(source, destination)
        events.append(("replace", Path(destination)))

    def recording_dirsync(path: Path) -> None:
        events.append(("dirsync", path))

    monkeypatch.setattr(atomic_write_module.os, "replace", recording_replace)
    monkeypatch.setattr(atomic_write_module, "_fsync_directory", recording_dirsync)

    atomic_write_text(target, "durable")

    assert target.read_text(encoding="utf-8") == "durable"
    assert events == [
        ("replace", target),
        ("dirsync", target.parent),
        ("dirsync", target.parent.parent),
        ("dirsync", tmp_path),
    ]


def test_atomic_write_stops_ancestor_sync_at_preexisting_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing_parent = tmp_path / "existing"
    existing_parent.mkdir()
    target = existing_parent / "created" / "state.json"
    synced: list[Path] = []

    monkeypatch.setattr(
        atomic_write_module, "_fsync_directory", lambda path: synced.append(path)
    )

    atomic_write_text(target, "durable")

    assert target.read_text(encoding="utf-8") == "durable"
    assert synced == [target.parent, existing_parent]


def test_atomic_write_does_not_dirsync_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "state.json"
    dirsync_calls: list[Path] = []

    def failing_replace(
        source: str | os.PathLike[str], destination: str | os.PathLike[str]
    ) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(atomic_write_module.os, "replace", failing_replace)
    monkeypatch.setattr(
        atomic_write_module, "_fsync_directory", lambda path: dirsync_calls.append(path)
    )

    with pytest.raises(OSError, match="replace failed"):
        atomic_write_text(target, "not committed")

    assert dirsync_calls == []
    assert not target.exists()
    assert list(tmp_path.glob(".state.json.*.tmp")) == []


@pytest.mark.skipif(os.name == "nt", reason="directory fsync is POSIX-only")
def test_fsync_directory_flushes_and_closes_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, object]] = []
    fake_fd = 91

    def fake_open(path: str | os.PathLike[str], flags: int) -> int:
        calls.append(("open", (Path(path), flags)))
        return fake_fd

    def fake_fsync(fd: int) -> None:
        calls.append(("fsync", fd))

    def fake_close(fd: int) -> None:
        calls.append(("close", fd))

    monkeypatch.setattr(atomic_write_module.os, "open", fake_open)
    monkeypatch.setattr(atomic_write_module.os, "fsync", fake_fsync)
    monkeypatch.setattr(atomic_write_module.os, "close", fake_close)

    atomic_write_module._fsync_directory(tmp_path)

    assert calls[0][0] == "open"
    opened_path, flags = calls[0][1]
    assert opened_path == tmp_path
    assert flags & os.O_RDONLY == os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        assert flags & os.O_DIRECTORY == os.O_DIRECTORY
    assert calls[1:] == [("fsync", fake_fd), ("close", fake_fd)]
