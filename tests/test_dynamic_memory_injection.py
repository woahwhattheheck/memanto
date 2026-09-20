from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from memanto.app.services.memory_read_service import MemoryReadService
from memanto.app.services.memory_write_service import MemoryWriteService
from memanto.cli.commands.memory_mgmt import _format_trusted_dynamic_memories
from memanto.cli.connect.updater import (
    _assert_dynamic_sync_write_scope,
    inject_dynamic_memories,
)

SENTINEL_START = "<!-- MEMANTO-DYNAMIC-MEMORIES -->"
SENTINEL_END = "<!-- /MEMANTO-DYNAMIC-MEMORIES -->"


def _instruction_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"before\n{SENTINEL_START}\nold\n{SENTINEL_END}\nafter\n")


def test_manual_sync_uses_the_single_local_connection(tmp_path):
    instruction_path = tmp_path / ".github" / "copilot-instructions.md"
    _instruction_file(instruction_path)
    connections = {
        "github-copilot": {
            "projects": [str(tmp_path.resolve())],
            "installed_global": False,
        }
    }

    with patch(
        "memanto.cli.config.manager.ConfigManager.load_connections",
        return_value=connections,
    ):
        inject_dynamic_memories(str(tmp_path), "- [INSTRUCTION] C:\\Users\\rule")

    content = instruction_path.read_text()
    assert "- [INSTRUCTION] C:\\Users\\rule" in content
    assert "old" not in content


def test_global_scope_never_updates_the_local_instruction(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    global_instruction = home / ".claude" / "CLAUDE.md"
    _instruction_file(global_instruction)
    local_instruction = tmp_path / "CLAUDE.md"
    _instruction_file(local_instruction)
    connections = {"claude-code": {"projects": [], "installed_global": True}}

    with patch(
        "memanto.cli.config.manager.ConfigManager.load_connections",
        return_value=connections,
    ):
        inject_dynamic_memories(
            str(tmp_path),
            "- [INSTRUCTION] Global rule",
            connection="claude-code",
            scope="global",
        )

    assert "Global rule" in global_instruction.read_text()
    assert "old" in local_instruction.read_text()


def test_sync_updates_all_local_connections(tmp_path):
    copilot_path = tmp_path / ".github" / "copilot-instructions.md"
    _instruction_file(copilot_path)
    claude_path = tmp_path / "CLAUDE.md"
    _instruction_file(claude_path)

    connections = {
        "github-copilot": {
            "projects": [str(tmp_path.resolve())],
            "installed_global": False,
        },
        "claude-code": {
            "projects": [str(tmp_path.resolve())],
            "installed_global": False,
        },
    }

    with patch(
        "memanto.cli.config.manager.ConfigManager.load_connections",
        return_value=connections,
    ):
        inject_dynamic_memories(str(tmp_path), "- [INSTRUCTION] Rule")

    assert "Rule" in copilot_path.read_text()
    assert "Rule" in claude_path.read_text()


def test_dynamic_formatter_excludes_imported_and_inferred_records():
    imported_note = "Keep team notes concise."
    formatted, trusted_count = _format_trusted_dynamic_memories(
        [
            {
                "type": "instruction",
                "content": imported_note,
                "provenance": "imported",
            },
            {
                "type": "goal",
                "content": "Use a weekly planning summary.",
                "provenance": "inferred",
            },
            {
                "type": "preference",
                "content": "Use pytest for Python regressions.",
                "provenance": "explicit_statement",
            },
            {
                "type": "instruction",
                "content": "Verify release artifacts before publishing.",
                "provenance": "validated",
            },
        ]
    )

    assert trusted_count == 2
    assert imported_note not in formatted
    assert "Use a weekly planning summary." not in formatted
    assert "- [PREFERENCE] Use pytest for Python regressions." in formatted
    assert "- [INSTRUCTION] Verify release artifacts before publishing." in formatted


def test_dynamic_formatter_fails_closed_when_provenance_is_missing():
    formatted, trusted_count = _format_trusted_dynamic_memories(
        [
            {
                "type": "instruction",
                "content": "Keep release notes concise.",
            }
        ]
    )

    assert trusted_count == 0
    assert formatted == ""


def _legacy_instruction_document():
    return {
        "id": "legacy-1",
        "text": "[INSTRUCTION] Legacy rule\n\nUse clear headings in summaries.",
        "metadata": {
            "memory_type": "instruction",
            "agent_id": "agent-1",
            "actor_id": "user",
            "source": "user",
            "confidence": 0.9,
            "status": "active",
        },
    }


def test_missing_provenance_stays_untrusted_through_real_read_normalization():
    client = MagicMock()
    client.documents.get.return_value = {"items": [_legacy_instruction_document()]}

    recalled = MemoryReadService(client).get_memory("legacy-1", "memanto_agent_agent-1")

    assert recalled is not None
    assert recalled["content"] == "Use clear headings in summaries."
    assert recalled["provenance"] == "unknown"

    formatted, trusted_count = _format_trusted_dynamic_memories([recalled])

    assert trusted_count == 0
    assert formatted == ""


def test_unrelated_edit_does_not_upgrade_missing_legacy_provenance():
    client = MagicMock()
    client.documents.get.return_value = {"items": [_legacy_instruction_document()]}
    client.documents.upload.return_value = {"status": "success"}

    MemoryWriteService(client).update_memory(
        "legacy-1",
        "memanto_agent_agent-1",
        {"content": "Updated legacy instruction body."},
    )

    uploaded = client.documents.upload.call_args.kwargs["documents"][0]
    assert "provenance" not in uploaded
    assert uploaded["text"].endswith("Updated legacy instruction body.")


def test_dynamic_sync_write_scope_accepts_project_target(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    target = project / "notes.md"
    _assert_dynamic_sync_write_scope(project, target, False)


def test_dynamic_sync_write_scope_rejects_outside_target(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    target = tmp_path / "notes.md"
    with pytest.raises(ValueError, match="outside project"):
        _assert_dynamic_sync_write_scope(project, target, False)
