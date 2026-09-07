"""Real Agno SDK integration. Synthetic fixtures are not bounty evidence."""

import hashlib
import sys
from dataclasses import asdict
from pathlib import Path

from agno.db.schemas.memory import UserMemory
from agno.db.sqlite import SqliteDb
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from convert import load_export  # noqa: E402
from export_agno import export_sqlite  # noqa: E402


def test_real_agno_scoped_export_preserves_dataclass_timestamps(tmp_path):
    database = tmp_path / "source.sqlite"
    engine = create_engine(URL.create("sqlite", database=str(database)))
    try:
        db = SqliteDb(db_engine=engine, memory_table="custom_memories")
        for user_id in ("alice", "bob"):
            saved = db.upsert_user_memory(
                UserMemory(
                    memory_id=f"memory-{user_id}",
                    memory=f"Synthetic {user_id} regression memory.",
                    user_id=user_id,
                    topics=["timezone"],
                    created_at=0,
                    updated_at=172800,
                )
            )
            assert saved is not None
        expected = [asdict(memory) for memory in db.get_user_memories(user_id="alice")]
    finally:
        engine.dispose()
    assert expected[0]["created_at"] == 0
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    output = tmp_path / "export.json"
    assert export_sqlite(database, "alice", output, "custom_memories") == 1
    export = load_export(output)
    assert export["memories"] == expected
    assert export["user_id"] == "alice"
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
