# Implementation guide

Start with `AGENTS.md`, the authoritative `docs/prompts/MASTER_PROMPT.md` and
`plans/IMPLEMENTATION_STATUS.md`. `plans/MASTER_PLAN.md` maps deliverables and gates.

Install with `uv sync --locked --extra dev`. Start `uv run streamlit run app.py` from the repo
root. Use `uv run pytest -q` and `uv run ruff check .` before each coherent feature commit.
No manual database edits are needed for normal use. Runtime source and keys must never be committed.

Implement feature changes at their owning layer: parsers emit `ParseResult`, services persist
and resolve, graph transforms view topology, UI presents it. Add a failing fixture reproducing
the desired behavior, implement the smallest complete change, run the suite and update docs/status.
Increment `PARSER_VERSION` whenever extraction semantics change to invalidate cached results.

Add new migrations in `Store.__init__`, preserving existing rows and original blobs. Use a
transaction and a new migration version. Stop the app and back up the entire data home before
deployment updates. Restore that backup with the prior code to roll back an incompatible migration.

Migration 3 adds `history_archives` without rewriting existing facts. History archiving journals
the compressed recovery body in the same transaction as metadata removal, so recovery remains
available if the filesystem publication is lost. Do not drop the journal when archived records
are absent. Before downgrading, restore archived history with the current version, or restore the
complete pre-upgrade data-home backup with its matching code. Recovery files alone are not a
complete workspace backup. Automated tests simulate filename loss and restart, not physical power loss.

Do not put imported code, API keys, rendered trees or complete inventories in session state.
Use file IDs and lazy source retrieval. New graph code must preserve evidence and cap work on
cycles/dense graphs. New provider code must honor privacy before any network request.
## Configuration transfer boundary

`configuration.py` owns `WorkspaceIdentity`, `PortableSettings`, `WorkspaceConfiguration`
and the export/import functions. The v2 allowlist includes parsing, import limits, parse workers,
graph limit and traversal depth. New portable fields require bounds/types and round-trip tests.
Legacy v1 imports ignore unrecognized/private settings; v2 rejects unknown settings. Validate
the complete document before creating the new workspace, then create identity/settings in one
transaction. Never serialize arbitrary settings, provider endpoints, credentials or privacy gates.
Restart Streamlit after changing cached Store class definitions during development.
Also restart after editing registered custom-component JavaScript: hot reload can retain an
older component asset even after Python re-registers the same name. Verify the running graph
in a real browser; AppTest cannot prove component rendering.

`VisualizationSettings` validates display preferences; `PortableSettings` includes that same
allowlist. Explorer passes one settings object to the live graph and offline HTML/JSON exports.
The component mount root can be a ShadowRoot/DocumentFragment with no `.style`; style the
contained graph element. Full SVG label fitting uses actual rendered text measurement.
Before reusing asset/source selectbox keys, clear selections absent from the current choices.
Key-based widget identity can otherwise preserve an ID from another workspace or filter.

`assistance_queue.py` owns current diagnostic eligibility, bounded context and `request_review`.
Its request path passes `expected_hash` through `assist_task` into `assist`, which snapshots and
checks the source before network use. Queue request button identity includes the preview hash
so an old click cannot authorize a newly reanalyzed file. `ui/assistance_result.py` reads existing
AI records by workspace/ID and owns shared explicit merge presentation. Keep future queues
offline on render; do not use model confidence to clear deterministic diagnostics.
