"""Read one user's Agno memories from a temporary, consistent SQLite snapshot."""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from typing import Any

from convert import FORMAT, render_export


def export_records(memories: list[Any], user_id: str, output: Path) -> int:
    """Serialize raw dataclass fields, validate scope and fidelity, and create a file."""
    export = {
        "format": FORMAT,
        "user_id": user_id,
        "memories": [asdict(memory) for memory in memories],
    }
    render_export(export)  # Reject invalid or oversized input before writing.
    with output.open("x", encoding="utf-8") as stream:
        json.dump(export, stream, ensure_ascii=True, sort_keys=True, indent=2)
        stream.write("\n")
    return len(memories)


def snapshot_sqlite(source: Path, destination: Path) -> None:
    """Use SQLite backup to include committed WAL data without modifying the source."""
    uri = source.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as reader:
        with closing(sqlite3.connect(destination)) as writer:
            reader.backup(writer)


def export_sqlite(
    source: Path, user_id: str, output: Path, memory_table: str | None = None
) -> int:
    """Use the official Agno database API only against a disposable copy."""
    from agno.db.sqlite import SqliteDb
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL

    with tempfile.TemporaryDirectory(prefix="agno-export-") as directory:
        snapshot = Path(directory) / "snapshot.sqlite"
        snapshot_sqlite(source, snapshot)
        engine = create_engine(URL.create("sqlite", database=str(snapshot)))
        try:
            db = SqliteDb(db_engine=engine, memory_table=memory_table)
            memories = db.get_user_memories(user_id=user_id)
            if not isinstance(memories, list):
                raise ValueError("Agno did not return a memory list")
            return export_records(memories, user_id, output)
        finally:
            engine.dispose()


def main() -> None:
    """Export one explicitly selected user, never all users by default."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--memory-table")
    args = parser.parse_args()
    try:
        count = export_sqlite(
            args.database, args.user_id, args.output, args.memory_table
        )
    except (OSError, ValueError, TypeError, ImportError, sqlite3.Error) as exc:
        parser.exit(2, f"Export failed ({type(exc).__name__}); no records printed.\n")
    print(f"Exported {count} scoped memories.")


if __name__ == "__main__":
    main()
