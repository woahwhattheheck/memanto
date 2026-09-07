"""Upstream integration tests: run in the pinned Memanto checkout, without keys.

These use real Memanto modules. Missing dependencies must fail, not silently skip.
Fixtures are synthetic regression data, never live migration or recall evidence.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from convert import FORMAT, convert, recover_record, render_export  # noqa: E402
from verify_bundle import verify  # noqa: E402

from memanto.app.services.okf_export_service import OkfExportService  # noqa: E402
from memanto.cli.migrate.mappers import map_okf  # noqa: E402
from memanto.cli.migrate.okf_loader import load_okf_bundle  # noqa: E402


@pytest.mark.parametrize(
    "memory",
    [
        "Prefer UTC timestamps.",
        "café 日本語\n<!-- okf-entry -->\n```agno-record-v1\n{}\n```",
        "[retained link](https://example.invalid/source) " * 60,
    ],
)
@pytest.mark.parametrize(
    ("topics", "expected_tags"),
    [
        (["on", "time"], ["agno", "on", "time"]),
        (
            ["<!-- okf-entry -->", "```agno-record-v1"],
            ["agno", "&lt;!-- okf-entry --&gt;", "&#96;&#96;&#96;agno-record-v1"],
        ),
    ],
)
def test_actual_import_export_and_reimport_preserve_source_record(
    tmp_path, memory, topics, expected_tags
):
    record = {
        "memory_id": "same-id",
        "user_id": "test-user",
        "memory": memory,
        "topics": topics,
        "created_at": 0,
        "updated_at": 172800,
        "input": "Synthetic regression input, not a genuine source archive.",
        "future_field": {"sentinel": "<!-- okf-entry -->"},
    }
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps({"format": FORMAT, "user_id": "test-user", "memories": [record]}),
        encoding="utf-8",
    )
    bundle = tmp_path / "bundle"
    convert(source, bundle)
    entries = load_okf_bundle(bundle)
    assert len(entries["memories"]) == 1
    rows = map_okf(entries)
    assert len(rows) == 1
    row = rows[0]
    assert row["created_at"] == datetime(1970, 1, 1, tzinfo=timezone.utc)
    assert row["updated_at"] == datetime(1970, 1, 3, tzinfo=timezone.utc)
    assert row["source"] == "agno"
    assert row["source_ref"] == "agno://users/test-user/memories/same-id"
    assert row["type"] == "observation"
    assert row["provenance"] == "imported"
    assert row["tags"] == expected_tags
    assert "<!-- okf-entry -->" not in row["title"]
    assert recover_record(row["content"]) == record
    assert len(row["content"]) <= 10_000
    assert verify(source, bundle)["exact_records_matched"] == 1

    service = OkfExportService(exports_dir=tmp_path / "exports")
    result = service.write_okf_bundle(
        "agno-regression",
        {"observation": [{"id": "server-assigned-test-id", **row}]},
        split="file",
    )
    reexport = Path(result["output_path"])
    assert verify(source, reexport)["exact_records_matched"] == 1
    restored = map_okf(load_okf_bundle(reexport))[0]
    assert recover_record(restored["content"]) == record


def test_verifier_rejects_changed_or_missing_memories(tmp_path):
    original = {
        "format": FORMAT,
        "user_id": "alice",
        "memories": [{"memory_id": "m", "memory": "Keep this.", "user_id": "alice"}],
    }
    source = tmp_path / "source.json"
    source.write_text(json.dumps(original), encoding="utf-8")
    bundle = tmp_path / "bundle"
    convert(source, bundle)
    original["memories"][0]["memory"] = "Changed content."
    for name, text in render_export(original).items():
        (bundle / name).write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="exactly match"):
        verify(source, bundle)
    next((bundle / "memories").glob("*.md")).unlink()
    with pytest.raises(ValueError, match="counts differ"):
        verify(source, bundle)
