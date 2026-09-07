"""Compare exact Agno source records with a bundle using Memanto's actual importer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from convert import load_export, recover_record, render_export


def verify(source: Path, bundle: Path) -> dict[str, Any]:
    """Check mapping and record fidelity, not semantic retrieval or agent answers."""
    from memanto.cli.migrate.mappers import map_okf, type_breakdown
    from memanto.cli.migrate.okf_loader import load_okf_bundle

    export = load_export(source)
    render_export(export)  # Apply the same strict schema and scope validation.
    expected = {record["memory_id"]: record for record in export["memories"]}
    entries = load_okf_bundle(bundle)
    rows = map_okf(entries)
    if len(entries["memories"]) != len(rows) or len(rows) != len(expected):
        raise ValueError("source, loaded, and mapped counts differ")
    recovered = {}
    for row in rows:
        record = recover_record(row["content"])
        identity = record.get("memory_id")
        if not isinstance(identity, str) or identity in recovered:
            raise ValueError("missing or duplicate source identity")
        recovered[identity] = record
    if recovered != expected:
        raise ValueError("mapped source records do not exactly match the export")
    return {
        "source_records": len(expected),
        "loaded_entries": len(entries["memories"]),
        "mapped_memories": len(rows),
        "skipped": 0,
        "exact_records_matched": len(recovered),
        "per_type": type_breakdown(rows),
        "semantic_recall_parity": "NOT RUN",
    }


def main() -> None:
    """Print only the fidelity summary; never print record contents on failure."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.source, args.bundle)
    except (OSError, ValueError, TypeError, ImportError) as exc:
        parser.exit(
            2, f"Verification failed ({type(exc).__name__}); no records printed.\n"
        )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
