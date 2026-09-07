"""Convert scoped Agno UserMemory dataclass exports into Memanto OKF bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

FORMAT = "agno-user-memory-v1"
RECORD_MARKER = "```agno-record-v1"
ENTRY_DELIMITER = "<!-- okf-entry -->"
# Reserve two upstream footer budgets within the 10,000-character limit.
# This covers import, export, and validation of that export (not unlimited hops).
MAX_BODY_CHARS = 8_000
_RECORD_RE = re.compile(r"(?m)^```agno-record-v1\n([^\n]+)\n```$")


def canonical(value: Any) -> str:
    """Encode deterministic JSON without introducing Markdown control sequences."""
    return (
        json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False)
        .replace("<", r"\u003c")
        .replace("`", r"\u0060")
    )


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON keys instead of silently dropping a source value."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _constant(_: str) -> Any:
    """Reject the non-JSON NaN/Infinity extensions accepted by Python's decoder."""
    raise ValueError("non-finite JSON number")


def load_export(path: Path) -> dict[str, Any]:
    """Read a strict UTF-8 export; report errors without echoing source records."""
    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_pairs,
        parse_constant=_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("export must be an object")
    return value


def _timestamp(value: Any) -> str | None:
    """Convert raw Agno epoch seconds to UTC, including zero; never guess a zone."""
    if value is None:
        return None
    if type(value) is not int:
        raise ValueError("timestamps must be integer epoch seconds or null")
    try:
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError("timestamp is outside the supported range") from exc


def _nonempty(value: Any, name: str) -> str:
    """Validate an identifier or memory without normalizing away source bytes."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value


def _display_text(value: str) -> str:
    """Keep control sequences out of fields that upstream later writes as YAML."""
    return value.replace(ENTRY_DELIMITER, "&lt;!-- okf-entry --&gt;").replace(
        RECORD_MARKER, "&#96;&#96;&#96;agno-record-v1"
    )


def render_export(export: dict[str, Any]) -> dict[str, str]:
    """Validate every record, then render deterministic files without any I/O."""
    if set(export) != {"format", "user_id", "memories"}:
        raise ValueError("export requires exactly format, user_id, and memories")
    if export["format"] != FORMAT:
        raise ValueError("unsupported export format")
    user_id = _nonempty(export["user_id"], "user_id")
    records = export["memories"]
    if not isinstance(records, list) or not records:
        raise ValueError("memories must be a nonempty list")
    # Validate the complete payload, including unknown future source fields.
    json.dumps(export, ensure_ascii=False, allow_nan=False).encode("utf-8")
    files: dict[str, str] = {}
    seen: set[str] = set()
    for position, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"record {position}: expected an object")
        memory_id = _nonempty(record.get("memory_id"), "memory_id")
        memory = _nonempty(record.get("memory"), "memory")
        if record.get("user_id") != user_id:
            raise ValueError(f"record {position}: user scope mismatch")
        if memory_id in seen:
            raise ValueError(f"record {position}: duplicate memory_id")
        seen.add(memory_id)
        topics = record.get("topics")
        if topics is None:
            topics = []
        if not isinstance(topics, list) or any(
            not isinstance(topic, str) for topic in topics
        ):
            raise ValueError(f"record {position}: topics must be strings or null")
        identity = canonical([user_id, memory_id])
        digest = hashlib.sha256(identity.encode("ascii")).hexdigest()
        frontmatter: dict[str, Any] = {
            "type": "observation",
            "title": _display_text(" ".join(memory.split()))[:80],
            "resource": (
                f"agno://users/{quote(user_id, safe='')}"
                f"/memories/{quote(memory_id, safe='')}"
            ),
            "tags": list(dict.fromkeys(["agno", *(_display_text(t) for t in topics)])),
            "x_memanto": {
                "type": "observation",
                "source": "agno",
                "provenance": "imported",
            },
        }
        created = _timestamp(record.get("created_at"))
        updated = _timestamp(record.get("updated_at"))
        if created is not None:
            frontmatter["timestamp"] = created
        if updated is not None:
            frontmatter["x_memanto"]["updated_at"] = updated
        # Upstream splits on the sentinel even inside prose or a JSON string.
        # Escape its display spelling; the exact source is in the JSON block.
        display = _display_text(memory)
        body = f"{display}\n\n{RECORD_MARKER}\n{canonical(record)}\n```"
        if len(body) > MAX_BODY_CHARS:
            raise ValueError(f"record {position}: content exceeds lossless size budget")
        # JSON is valid YAML, with unambiguous quoting for dates and booleans.
        files[f"memories/{digest}.md"] = (
            f"---\n{canonical(frontmatter)}\n---\n\n{body}\n"
        )
    return dict(sorted(files.items()))


def recover_record(content: str) -> dict[str, Any]:
    """Recover one exact source record from a converted or re-exported body."""
    matches = _RECORD_RE.findall(content)
    if len(matches) != 1:
        raise ValueError("expected exactly one complete Agno source record")
    record = json.loads(matches[0], object_pairs_hook=_pairs, parse_constant=_constant)
    if not isinstance(record, dict):
        raise ValueError("embedded source record must be an object")
    return record


def convert(source: Path, output: Path) -> dict[str, Any]:
    """Write a new bundle only after complete validation; never replace a bundle."""
    export = load_export(source)
    files = render_export(export)
    records = sorted(export["memories"], key=lambda record: record["memory_id"])
    report = {
        "format": FORMAT,
        "source_records": len(records),
        "okf_documents": len(files),
        "per_type": {"observation": len(records)},
        "records_sha256": hashlib.sha256(
            canonical(records).encode("ascii")
        ).hexdigest(),
        "source_bytes": source.stat().st_size,
        "okf_document_bytes": sum(len(text.encode("utf-8")) for text in files.values()),
        "live_import": "NOT RUN",
        "recall_parity": "NOT RUN",
        "cost_token_latency_savings": None,
    }
    output.mkdir(mode=0o700)  # Refuse an existing or missing-parent destination.
    try:
        (output / "memories").mkdir()
        for name, text in files.items():
            (output / name).write_text(text, encoding="utf-8", newline="\n")
        (output / "manifest.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except BaseException:
        shutil.rmtree(output)
        raise
    return report


def main() -> None:
    """CLI entry point; emit only counts and generic validation failures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        report = convert(args.source, args.output)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(
            2, f"Conversion failed ({type(exc).__name__}); no records printed.\n"
        )
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
