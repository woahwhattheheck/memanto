# Agno user memories → Memanto OKF

A scoped Python adapter for Memanto issue #1609, Path B. It converts **raw Agno
`UserMemory` dataclass fields** into an OKF bundle accepted by the existing
`memanto migrate okf` interface. It adds no core provider or model runtime.

This is an **intake-stage implementation**, not a complete contest submission.
The regression fixtures are synthetic. No live Agno archive, Moorcheh retrieval
result, demo video, social post, bounty claim, or sponsor approval is included.

## Source revisions

Memanto base: `06615f09c536336e629e34589dc125495cba3109`.
Agno API inspected: `8f36eaf2d18e91afa7b327eec66a3cd3685dcb87` (`3.0.6` in its project metadata).
Agno is optional for file conversion and required only for database export.
The converter uses Python's standard library; offline tests add pytest and PyYAML.
Use a disposable cloud environment, not the owner's PC.

## Setup and regression commands

From a checkout of the pinned Memanto revision with this patch applied:

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[all]'
python -m pip install -r examples/migrations/agno-user-memory/requirements-source.txt

# No source SDK, Memanto imports, API keys, or network calls in this file:
python -m pytest -q examples/migrations/agno-user-memory/tests/test_convert.py

# Real SDK/importer integration; missing dependencies must fail, not skip:
python -m pytest -q examples/migrations/agno-user-memory/tests/test_agno.py
python -m pytest -q examples/migrations/agno-user-memory/tests/test_memanto.py

python -m ruff check examples/migrations/agno-user-memory
python -m ruff format --check examples/migrations/agno-user-memory
python -m pytest -q tests/test_okf.py
```

Dependency installation was exercised in an isolated Python 3.11 GitHub Actions
runner on September 7, 2026. See the accompanying validation receipt for results.
`requirements-source.txt` pins Agno's source and selects only its SQL extra, not
model-provider, `all`, or local-inference extras. Transitive dependencies are not
lockfile-pinned. Do not install llama.cpp-related packages or use an owner-PC
runtime to complete these commands.

## Genuine-source workflow

Only use a database you are authorized to read. Choose one explicit user and,
when necessary, the existing custom memory table. Keep the output private.
Replace the non-secret paths and user ID below with the intended source values:

```bash
EXAMPLE=examples/migrations/agno-user-memory
mkdir -m 700 "$EXAMPLE/private-run"
python "$EXAMPLE/export_agno.py" /path/to/owned-agno.sqlite \
  "$EXAMPLE/private-run/source.json" --user-id exact-user-id
# Add --memory-table existing-table-name when Agno uses a custom table.
python "$EXAMPLE/convert.py" "$EXAMPLE/private-run/source.json" \
  "$EXAMPLE/private-run/okf"
python "$EXAMPLE/verify_bundle.py" "$EXAMPLE/private-run/source.json" \
  "$EXAMPLE/private-run/okf" > "$EXAMPLE/private-run/fidelity.json"
memanto migrate okf "$EXAMPLE/private-run/okf" --dry-run
```

The exporter opens the original SQLite database read-only, takes a consistent
SQLite backup including committed WAL data, and lets Agno read the disposable
copy. SDK initialization/schema changes cannot modify the original database.
Normal SQLite read locks or sidecar handling may still occur. It does not call
an LLM, fetch remote memories, or export all users implicitly.

The exported JSON envelope is exactly `format`, `user_id`, and `memories`, with
`format` set to `agno-user-memory-v1`. Each list item is `dataclasses.asdict()`
of an Agno `UserMemory`, not `UserMemory.to_dict()`. At the inspected revision,
`to_dict()` converts epochs through the machine's local timezone without a zone
suffix; the adapter retains raw epoch seconds and emits explicit UTC timestamps.
Legacy timezone-naive JSON exports are rejected rather than interpreted by guess.

The OKF subcommand at the pinned Memanto revision has **no `--report` option**.
Its dry run maps locally without a target agent or API client, although it writes
local preview files to Memanto's configured data directory. The conversion
manifest reports measured source/document byte counts, not invented savings.

Live import, recall, and export must be separately authorized after the sponsor
and AI-policy gates are satisfied. A dedicated Memanto agent must be used for a
real run. Verify any subsequent exported bundle using the same command:

```bash
python examples/migrations/agno-user-memory/verify_bundle.py \
  /private/source.json /private/actual-memanto-export
```

This measures exact source-record fidelity through Memanto's loader and mapper.
It is **not** a semantic recall test. The contest's before/after golden questions
must actually query Agno and Memanto; content presence is not a substitute.

## Mapping and limitations

| Agno field | Representation |
| --- | --- |
| `memory` | Readable body plus an exact JSON source record |
| `memory_id`, `user_id` | Percent-encoded `agno://` resource; SHA-256 identity filename |
| `topics` | Deduplicated OKF tags; original list remains in the source record |
| `created_at` | UTC `timestamp`, including Unix epoch zero |
| `updated_at` | UTC `x_memanto.updated_at` |
| Memory type | Conservative `observation`; no unsupported semantic inference |
| Source and provenance | `agno`, `imported` |
| `input`, `feedback`, agent/team IDs, future fields | Exact canonical JSON in the body |

Memanto's supporting-data footer truncates oversized metadata. Keeping the
complete record in the body avoids depending on that footer for fidelity.
The JSON is deterministic and escapes Markdown control characters. The exact
`<!-- okf-entry -->` sentinel is escaped in displayed text, titles, and tags
because the pinned loader splits on that substring. The JSON still reconstructs the original value.
This is a producer-side compatibility rule, not a change to the upstream loader.

All records are validated before creating a bundle. Duplicate IDs, wrong user
scope, ambiguous JSON, non-finite numbers, invalid timestamps/topics, empty
exports, and oversized records fail explicitly. Output paths are derived from
identity hashes, not memory titles or raw IDs. An existing destination is never
overwritten. An ordinary write failure removes only the newly created bundle.
The output directory must have an existing parent. Publication is not atomic
against concurrent readers; consumers must wait for successful conversion.

Bodies over **8,000 characters** are rejected, reserving room within Memanto's
10,000-character limit for the initial import footer and one export/reimport
verification. This is not a guarantee for arbitrarily many migration cycles:
upstream currently appends another supporting-data footer on each import.
Server-assigned Memanto IDs are not preserved; original Agno IDs are.
Full original JSON bytes/whitespace are not preserved; decoded record fields are.

**Privacy:** source records intentionally include `input`, feedback and IDs.
This is not a sanitizer. Never add private source databases, exports, logs,
credentials, or unreviewed memory bundles to a PR. A public sample must come from
an actual, intentionally shareable tool run and be reviewed before publication.
The adapter's own validation errors omit record values; third-party SDK/CLI
logging is outside that guarantee.

## Submission gates

Issue #1609 advertises $200 USD for **one winning entry**, not for every merged
adapter, with a September 15, 2026 23:59 UTC deadline. A linked BountyHub account
and claim, contributor onboarding, genuine-source evidence, live pipeline video,
social links and recall parity are required by the issue. None is implied by
these tests. Confirm the current sponsor offer and full onboarding AI rules
before proposing this entry publicly. Do not use `Closes #1609` for this partial
contest deliverable.

Sources: https://github.com/moorcheh-ai/memanto/issues/1609 and the repository's
CONTRIBUTING.md. The chat handoff contains detailed source links and gate status.

### Re-export control sequences

Titles, displayed memory text, and projected tags escape the OKF entry delimiter
and the embedded-record fence marker. Escaping only the initial JSON frontmatter
is insufficient: Memanto's exporter decodes those strings and serializes them as
YAML on the next hop. The original title source and original topics remain exact
in the embedded canonical Agno record; ordinary projected tags are unchanged.
