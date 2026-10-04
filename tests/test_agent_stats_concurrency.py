"""Agent statistics must compose with other updates and completed deletion."""

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timezone
from threading import Event

import pytest

from memanto.app.models.session import AgentInfo, AgentPattern
from memanto.app.services.agent_service import AgentService
from memanto.app.utils.errors import AgentNotFoundError


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def reject_network(*args, **kwargs):
        raise AssertionError("Agent statistics must not use the network")

    monkeypatch.setattr("socket.socket.connect", reject_network)
    monkeypatch.setattr("socket.getaddrinfo", reject_network)


def _seed(service, agent_id="stats-agent"):
    service._save_agent(
        AgentInfo(
            agent_id=agent_id,
            namespace=f"memanto_agent_{agent_id}",
            pattern=AgentPattern.SUPPORT,
            description="Retained agent metadata",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )


def _pause_after_read(monkeypatch, service):
    loaded = Event()
    resume = Event()
    original = service.get_agent

    def read_then_pause(agent_id):
        agent = original(agent_id)
        loaded.set()
        assert resume.wait(5), "statistics update was never resumed"
        return agent

    monkeypatch.setattr(service, "get_agent", read_then_pause)
    return loaded, resume


def _allow_competing_operation(future):
    # The broken implementation permits the competing operation to complete
    # before the paused write. Correct serialization waits for its release.
    try:
        future.result(timeout=0.25)
    except FutureTimeout:
        pass


def test_concurrent_stats_updates_preserve_both_increments(tmp_path, monkeypatch):
    first = AgentService(tmp_path)
    second = AgentService(tmp_path)
    _seed(first)
    loaded, resume = _pause_after_read(monkeypatch, first)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_result = pool.submit(
            first.update_agent_stats, "stats-agent", increment_session_count=True
        )
        try:
            assert loaded.wait(5), "first update did not read the agent"
            second_result = pool.submit(
                second.update_agent_stats,
                "stats-agent",
                increment_session_count=True,
            )
            _allow_competing_operation(second_result)
        finally:
            resume.set()
        results = [first_result.result(timeout=5), second_result.result(timeout=5)]

    assert sorted(agent.session_count for agent in results) == [1, 2]
    assert second.get_agent("stats-agent").session_count == 2


def test_completed_delete_is_not_overwritten_by_inflight_stats(tmp_path, monkeypatch):
    updater = AgentService(tmp_path)
    deleter = AgentService(tmp_path)
    _seed(updater)
    loaded, resume = _pause_after_read(monkeypatch, updater)

    with ThreadPoolExecutor(max_workers=2) as pool:
        updated = pool.submit(
            updater.update_agent_stats, "stats-agent", increment_session_count=True
        )
        try:
            assert loaded.wait(5), "update did not read the agent"
            deleted = pool.submit(deleter.delete_agent, "stats-agent")
            _allow_competing_operation(deleted)
        finally:
            resume.set()
        updated.result(timeout=5)
        deleted.result(timeout=5)

    assert deleter.get_agent("stats-agent") is None
    assert not deleter.agent_exists("stats-agent")


def test_update_after_delete_keeps_agent_absent(tmp_path):
    updater = AgentService(tmp_path)
    deleter = AgentService(tmp_path)
    _seed(updater)
    deleter.delete_agent("stats-agent")

    with pytest.raises(AgentNotFoundError):
        updater.update_agent_stats("stats-agent", increment_session_count=True)

    assert not updater.agent_exists("stats-agent")


def test_stats_update_preserves_metadata_and_optional_increment(tmp_path):
    service = AgentService(tmp_path)
    _seed(service)
    timestamp = datetime(2026, 1, 2, tzinfo=timezone.utc)

    updated = service.update_agent_stats("stats-agent", last_session=timestamp)

    assert updated.session_count == 0
    assert updated.last_session == timestamp
    assert updated.description == "Retained agent metadata"
    assert updated.created_at == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert service.get_agent("stats-agent") == updated


def test_paused_update_does_not_block_another_agent(tmp_path, monkeypatch):
    first = AgentService(tmp_path)
    second = AgentService(tmp_path)
    _seed(first)
    _seed(second, "other-agent")
    loaded, resume = _pause_after_read(monkeypatch, first)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_result = pool.submit(
            first.update_agent_stats, "stats-agent", increment_session_count=True
        )
        try:
            assert loaded.wait(5), "first update did not read the agent"
            other_result = pool.submit(
                second.update_agent_stats,
                "other-agent",
                increment_session_count=True,
            )
            assert other_result.result(timeout=2).session_count == 1
        finally:
            resume.set()
        assert first_result.result(timeout=5).session_count == 1
