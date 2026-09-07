"""Offline regression tests. The records here are synthetic, not bounty evidence."""

import copy
import json
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from convert import (  # noqa: E402
    ENTRY_DELIMITER,
    FORMAT,
    RECORD_MARKER,
    convert,
    load_export,
    recover_record,
    render_export,
)
from export_agno import export_records, snapshot_sqlite  # noqa: E402


@pytest.fixture
def export():
    return {
        "format": FORMAT,
        "user_id": "alice",
        "memories": [
            {
                "memory_id": "m1",
                "memory": "Use PostgreSQL 16.\nPrefer UTC timestamps.",
                "user_id": "alice",
                "topics": ["database", "database", "on"],
                "created_at": 0,
                "updated_at": 172800,
                "input": "Remember the database and timezone choices.",
                "feedback": None,
                "agent_id": "planner",
                "team_id": None,
                "future_field": {"nested": [False, None, 3]},
            }
        ],
    }


def document(export):
    return next(iter(render_export(export).values()))


def frontmatter(text):
    return yaml.safe_load(text.split("---\n", 2)[1])


def test_exact_record_round_trip_including_future_fields(export):
    before = copy.deepcopy(export)
    assert recover_record(document(export)) == export["memories"][0]
    assert export == before


def test_epoch_zero_utc_and_quoted_yaml_scalars(export):
    fm = frontmatter(document(export))
    assert fm["timestamp"] == "1970-01-01T00:00:00+00:00"
    assert fm["x_memanto"]["updated_at"] == "1970-01-03T00:00:00+00:00"
    assert fm["tags"] == ["agno", "database", "on"]
    assert fm["x_memanto"]["provenance"] == "imported"


def test_null_timestamps_are_not_invented(export):
    export["memories"][0].update(created_at=None, updated_at=None, topics=None)
    fm = frontmatter(document(export))
    assert "timestamp" not in fm
    assert "updated_at" not in fm["x_memanto"]
    assert fm["tags"] == ["agno"]


def test_unicode_and_reserved_markers_are_lossless(export):
    record = export["memories"][0]
    record["memory"] = (
        f"  café 日本語 🐜\n{ENTRY_DELIMITER}\n"
        f'{RECORD_MARKER}\n{{"fake": true}}\n```\n---\n'
    )
    record["future_field"] = {"sentinel": ENTRY_DELIMITER, "fence": RECORD_MARKER}
    text = document(export)
    assert ENTRY_DELIMITER not in text
    assert text.count(RECORD_MARKER) == 1
    assert recover_record(text) == record


def test_identity_based_paths_do_not_collide_or_depend_on_order(export):
    other = copy.deepcopy(export["memories"][0])
    other["memory_id"] = "../../index"
    export["memories"].append(other)
    files = render_export(export)
    assert len(files) == 2
    assert files == render_export(
        {**export, "memories": list(reversed(export["memories"]))}
    )
    assert all(Path(path).parent == Path("memories") for path in files)
    assert all(len(Path(path).stem) == 64 for path in files)
    other["memory"] = "A correction to the same memory."
    assert set(render_export(export)) == set(files)


@pytest.mark.parametrize("value", [True, False, "2026-01-01", 0.0, 10**30])
def test_invalid_timestamps_do_not_become_plausible_dates(export, value):
    export["memories"][0]["created_at"] = value
    with pytest.raises(ValueError):
        render_export(export)


@pytest.mark.parametrize("value", ["database", [3], [None], {"tag": "x"}])
def test_topics_are_not_silently_coerced(export, value):
    export["memories"][0]["topics"] = value
    with pytest.raises(ValueError):
        render_export(export)


@pytest.mark.parametrize(
    "field,value", [("memory", "  "), ("memory_id", None), ("user_id", "bob")]
)
def test_bad_records_fail_before_writing(export, tmp_path, field, value):
    export["memories"][0][field] = value
    source = tmp_path / "source.json"
    source.write_text(json.dumps(export))
    output = tmp_path / "bundle"
    with pytest.raises(ValueError):
        convert(source, output)
    assert not output.exists()


def test_duplicate_ids_are_not_overwritten(export):
    export["memories"].append(copy.deepcopy(export["memories"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        render_export(export)


def test_oversized_second_record_cannot_produce_partial_bundle(export, tmp_path):
    second = copy.deepcopy(export["memories"][0])
    second.update(memory_id="m2", memory="x" * 10000)
    export["memories"].append(second)
    source = tmp_path / "source.json"
    source.write_text(json.dumps(export))
    with pytest.raises(ValueError, match="size budget"):
        convert(source, tmp_path / "bundle")
    assert not (tmp_path / "bundle").exists()


@pytest.mark.parametrize(
    "text",
    ['{"a":1,"a":2}', '{"nested":{"a":1,"a":2}}', '{"x":NaN}', '{"x":Infinity}', "[]"],
)
def test_invalid_or_ambiguous_json_is_rejected(tmp_path, text):
    source = tmp_path / "source.json"
    source.write_text(text)
    with pytest.raises(ValueError):
        load_export(source)


def test_write_report_and_no_overwrite(export, tmp_path):
    source = tmp_path / "source.json"
    source.write_text(json.dumps(export), encoding="utf-8")
    bundle = tmp_path / "bundle"
    report = convert(source, bundle)
    contents = {p.name: p.read_bytes() for p in bundle.rglob("*") if p.is_file()}
    assert report["source_records"] == report["okf_documents"] == 1
    assert report["live_import"] == "NOT RUN"
    assert report["cost_token_latency_savings"] is None
    with pytest.raises(FileExistsError):
        convert(source, bundle)
    assert contents == {
        p.name: p.read_bytes() for p in bundle.rglob("*") if p.is_file()
    }


def test_cli_does_not_echo_private_content(export, tmp_path):
    export["memories"][0]["topics"] = ["PRIVATE_MARKER", 1]
    source = tmp_path / "source.json"
    source.write_text(json.dumps(export))
    script = Path(__file__).resolve().parents[1] / "convert.py"
    result = subprocess.run(
        [sys.executable, str(script), str(source), str(tmp_path / "out")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "PRIVATE_MARKER" not in result.stdout + result.stderr
    assert not (tmp_path / "out").exists()


def test_truncated_or_ambiguous_record_block_is_not_accepted(export):
    text = document(export)
    with pytest.raises(ValueError):
        recover_record(text.rsplit("```", 1)[0])
    with pytest.raises(ValueError):
        recover_record(text + "\n" + text)


def test_sqlite_snapshot_includes_wal_and_never_writes_to_original(tmp_path):
    source, snapshot = tmp_path / "source.sqlite", tmp_path / "snapshot.sqlite"
    connection = sqlite3.connect(source)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE memories (value TEXT)")
        connection.execute("INSERT INTO memories VALUES ('committed WAL value')")
        connection.commit()
        snapshot_sqlite(source, snapshot)
        with sqlite3.connect(snapshot) as copied:
            assert (
                copied.execute("SELECT value FROM memories").fetchone()[0]
                == "committed WAL value"
            )
            copied.execute("DELETE FROM memories")
        assert connection.execute("SELECT count(*) FROM memories").fetchone()[0] == 1
    finally:
        connection.close()


def test_snapshot_of_missing_source_does_not_create_it(tmp_path):
    source = tmp_path / "missing.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        snapshot_sqlite(source, tmp_path / "copy.sqlite")
    assert not source.exists()


def test_raw_dataclass_export_preserves_epoch_zero(tmp_path):
    @dataclass
    class FixtureMemory:
        memory: str = "Use UTC."
        memory_id: str = "m1"
        user_id: str = "alice"
        created_at: int = 0

    output = tmp_path / "source.json"
    assert export_records([FixtureMemory()], "alice", output) == 1
    assert load_export(output)["memories"][0]["created_at"] == 0
    with pytest.raises(FileExistsError):
        export_records([FixtureMemory()], "alice", output)


def test_output_failure_removes_only_new_bundle(export, tmp_path, monkeypatch):
    source = tmp_path / "source.json"
    source.write_text(json.dumps(export), encoding="utf-8")
    sibling = tmp_path / "keep.txt"
    sibling.write_text("unrelated", encoding="utf-8")
    original_write = Path.write_text

    def fail_manifest(path, *args, **kwargs):
        if path.name == "manifest.json":
            raise OSError("simulated output failure")
        return original_write(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_manifest)
    with pytest.raises(OSError):
        convert(source, tmp_path / "bundle")
    assert not (tmp_path / "bundle").exists()
    assert sibling.read_text(encoding="utf-8") == "unrelated"
    assert source.exists()


def test_report_byte_counts_match_written_markdown(export, tmp_path):
    export["memories"][0]["memory"] = "café 日本語 🐜\nUse UTC."
    source = tmp_path / "source.json"
    source.write_text(json.dumps(export), encoding="utf-8")
    output = tmp_path / "bundle"
    report = convert(source, output)
    assert report["source_bytes"] == len(source.read_bytes())
    assert report["okf_document_bytes"] == sum(
        len(path.read_bytes()) for path in output.rglob("*.md")
    )


def test_decoded_projection_fields_do_not_reintroduce_control_sequences():
    """Re-export serializes decoded fields as YAML, not our escaped JSON."""
    record = {
        "memory_id": "control-sequences",
        "user_id": "alice",
        "memory": "<!-- okf-entry --> followed by ```agno-record-v1",
        "topics": ["<!-- okf-entry -->", "```agno-record-v1"],
    }
    docs = render_export({"format": FORMAT, "user_id": "alice", "memories": [record]})
    text = next(iter(docs.values()))
    metadata = yaml.safe_load(text.split("---\n", 2)[1])
    assert "<!-- okf-entry -->" not in yaml.safe_dump(metadata)
    assert "```agno-record-v1" not in yaml.safe_dump(metadata)
    assert recover_record(text) == record
