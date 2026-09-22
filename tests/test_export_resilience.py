"""Regression coverage: ``export_memory_md`` must not silently write an
empty export when every ``recall`` call fails (e.g. the on-prem backend is
unreachable), and ``sync_memory_to_project`` must fall back to a
previous good export instead of overwriting a project's ``MEMORY.md`` with
nothing.

Before this fix, a total-outage export produced an all-empty
``memories_by_type`` (each per-type ``recall`` exception was swallowed) and
still wrote it out — every call to ``memanto memory sync`` during a brief
backend outage silently wiped the agent's exported context and the
project's ``MEMORY.md``.
"""

from unittest.mock import MagicMock

import pytest

import memanto.cli.client.direct_client as direct_mod
import memanto.cli.client.sdk_client as sdk_mod
from memanto.app.services.memory_export_service import MEMORY_TYPE_ORDER

DirectClient = direct_mod.DirectClient
SdkClient = sdk_mod.SdkClient


def _build_client(client_cls, monkeypatch, tmp_path):
    """Construct *client_cls* with session validation stubbed out and
    ``Path.home()`` redirected to *tmp_path*. ``Path`` is the same class
    object everywhere it's imported, so this one patch also covers
    ``MemoryExportService``'s default ``exports_dir`` — export writes and
    ``sync_memory_to_project``'s cache lookup end up at the same
    ``tmp_path/.memanto/exports/`` regardless of which module reads
    ``Path.home()``."""
    module = direct_mod if client_cls is DirectClient else sdk_mod
    monkeypatch.setattr(module.Path, "home", classmethod(lambda cls: tmp_path))

    client = client_cls(api_key="test-key")
    monkeypatch.setattr(
        client, "_get_validated_session_for_agent", lambda agent_id: None
    )
    return client


class TestExportMemoryMdRefusesEmptyOnTotalFailure:
    @pytest.mark.parametrize("client_cls", [SdkClient, DirectClient])
    def test_raises_when_every_recall_fails(self, client_cls, monkeypatch, tmp_path):
        client = _build_client(client_cls, monkeypatch, tmp_path)
        monkeypatch.setattr(
            client, "recall", MagicMock(side_effect=ConnectionError("backend down"))
        )

        with pytest.raises(ConnectionError, match="unreachable"):
            client.export_memory_md(agent_id="test-agent")

    @pytest.mark.parametrize("client_cls", [SdkClient, DirectClient])
    def test_partial_failure_refuses_incomplete_export(
        self, client_cls, monkeypatch, tmp_path
    ):
        """One failed type must not be represented as a genuinely empty type."""
        client = _build_client(client_cls, monkeypatch, tmp_path)

        def fake_recall(agent_id, query, limit, type):
            if type == [MEMORY_TYPE_ORDER[0]]:
                raise ConnectionError("flaky")
            return {"memories": [{"content": "ok"}]}

        monkeypatch.setattr(client, "recall", MagicMock(side_effect=fake_recall))

        with pytest.raises(
            ConnectionError,
            match=f"incomplete.*{MEMORY_TYPE_ORDER[0]}|{MEMORY_TYPE_ORDER[0]}.*incomplete",
        ):
            client.export_memory_md(agent_id="test-agent")


class TestSyncFallsBackToCache:
    """Sync refreshes first, so a cached export is only reused when the
    refresh fails — never in place of memories written this session."""

    @pytest.mark.parametrize("client_cls", [SdkClient, DirectClient])
    def test_cache_used_when_backend_down(self, client_cls, monkeypatch, tmp_path):
        client = _build_client(client_cls, monkeypatch, tmp_path)

        cache_file = tmp_path / ".memanto" / "exports" / "test-agent_memory.md"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("### Some Memory\n\ngood content\n", encoding="utf-8")

        monkeypatch.setattr(
            client, "recall", MagicMock(side_effect=ConnectionError("backend down"))
        )

        project_dir = tmp_path / "project"
        result = client.sync_memory_to_project(
            agent_id="test-agent", project_dir=str(project_dir)
        )

        client.recall.assert_called()
        assert result["source"] == "stale-cache"
        assert result["total_memories"] == 1
        written = (project_dir / "MEMORY.md").read_text(encoding="utf-8")
        assert "good content" in written

    @pytest.mark.parametrize("client_cls", [SdkClient, DirectClient])
    def test_fresh_export_replaces_stale_cache(self, client_cls, monkeypatch, tmp_path):
        """A cache written before this session must not shadow new memories."""
        client = _build_client(client_cls, monkeypatch, tmp_path)

        cache_file = tmp_path / ".memanto" / "exports" / "test-agent_memory.md"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("### Old Memory\n\nstale content\n", encoding="utf-8")

        monkeypatch.setattr(
            client,
            "recall",
            MagicMock(return_value={"memories": [{"content": "fresh content"}]}),
        )

        project_dir = tmp_path / "project"
        result = client.sync_memory_to_project(
            agent_id="test-agent", project_dir=str(project_dir)
        )

        assert result["source"] == "fresh"
        written = (project_dir / "MEMORY.md").read_text(encoding="utf-8")
        assert "stale content" not in written
        assert "fresh content" in written

    def test_raises_when_no_cache_and_backend_down(self, monkeypatch, tmp_path):
        client = _build_client(SdkClient, monkeypatch, tmp_path)
        monkeypatch.setattr(
            client, "recall", MagicMock(side_effect=ConnectionError("backend down"))
        )

        with pytest.raises(ConnectionError):
            client.sync_memory_to_project(
                agent_id="test-agent", project_dir=str(tmp_path / "project")
            )

    @pytest.mark.parametrize("client_cls", [SdkClient, DirectClient])
    def test_rejects_path_traversal_before_cache_lookup(
        self, client_cls, monkeypatch, tmp_path
    ):
        client = _build_client(client_cls, monkeypatch, tmp_path)

        # Patch get_data_dir in the specific client module to prove it's never reached
        mock_get_data_dir = MagicMock()
        monkeypatch.setattr(f"{client_cls.__module__}.get_data_dir", mock_get_data_dir)

        with pytest.raises(ValueError, match="invalid characters"):
            client.sync_memory_to_project(
                agent_id="../outside", project_dir=str(tmp_path / "project")
            )

        mock_get_data_dir.assert_not_called()


def _symlink_memory_target(project_dir, victim):
    """Create a repo-controlled MEMORY.md symlink, or skip if unsupported."""
    project_dir.mkdir(parents=True, exist_ok=True)
    victim.write_text("outside victim\\n", encoding="utf-8")
    before = victim.read_bytes()
    target = project_dir / "MEMORY.md"
    try:
        target.symlink_to(victim)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    return target, before


class TestSyncDoesNotFollowDestinationSymlink:
    """Project sync must replace MEMORY.md itself, never its symlink target."""

    @pytest.mark.parametrize("client_cls", [SdkClient, DirectClient])
    def test_stale_cache_sync_replaces_symlink_without_touching_victim(
        self, client_cls, monkeypatch, tmp_path
    ):
        client = _build_client(client_cls, monkeypatch, tmp_path)
        cache_file = tmp_path / ".memanto" / "exports" / "test-agent_memory.md"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            "### Cached Memory\\n\\nsafe cached content\\n", encoding="utf-8"
        )
        monkeypatch.setattr(
            client, "recall", MagicMock(side_effect=ConnectionError("backend down"))
        )

        project_dir = tmp_path / "project"
        victim = tmp_path / "outside.md"
        target, before = _symlink_memory_target(project_dir, victim)

        result = client.sync_memory_to_project(
            agent_id="test-agent", project_dir=str(project_dir)
        )

        assert result["source"] == "stale-cache"
        assert victim.read_bytes() == before
        assert not target.is_symlink()
        assert "safe cached content" in target.read_text(encoding="utf-8")

    @pytest.mark.parametrize("client_cls", [SdkClient, DirectClient])
    def test_fresh_sync_replaces_symlink_without_touching_victim(
        self, client_cls, monkeypatch, tmp_path
    ):
        client = _build_client(client_cls, monkeypatch, tmp_path)
        monkeypatch.setattr(
            client,
            "recall",
            MagicMock(return_value={"memories": [{"content": "fresh safe content"}]}),
        )

        project_dir = tmp_path / "project"
        victim = tmp_path / "outside.md"
        target, before = _symlink_memory_target(project_dir, victim)

        result = client.sync_memory_to_project(
            agent_id="test-agent", project_dir=str(project_dir)
        )

        assert result["source"] == "fresh"
        assert victim.read_bytes() == before
        assert not target.is_symlink()
        assert "fresh safe content" in target.read_text(encoding="utf-8")
