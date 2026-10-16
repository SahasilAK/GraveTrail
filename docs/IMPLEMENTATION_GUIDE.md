# Implementation guide

Start with `AGENTS.md`, the authoritative `docs/prompts/MASTER_PROMPT.md` and
`plans/IMPLEMENTATION_STATUS.md`. `plans/MASTER_PLAN.md` maps deliverables and gates.

Install with `uv sync --locked --extra dev`. Start `uv run dataforge-ui` from the repo
root (direct `uv run streamlit run app.py` remains available). Use `uv run pytest -q` and
`uv run ruff check .` before each coherent feature commit. Installation, packaging and
operations commands live in [SETUP_AND_DEPLOYMENT.md](SETUP_AND_DEPLOYMENT.md).
No manual database edits are needed for normal use. Runtime source and keys must never be committed.
Use `dataforge --home PATH ...` for independent CLI/MCP access only after stopping another
owner of that home; installed UI and CLI defaults differ, so configure home explicitly.

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

`ui/themes.py` owns eight named native presets (four palettes × dark/light), current detection
and atomic theme-only configuration updates. Explicit presets use root `theme.base` and colors;
dual appearance sections are consolidated so a dark choice applies even after browser Light
selection. Non-color layout/sidebar overrides are retained. A bounded native fragment waits
for `st.get_option` to reflect the configuration watcher before rerunning; no private theme API
or injected CSS is used. Theme is app-wide deployment configuration, not workspace data.
The local config must be writable. Installed/frozen builds copy the default into the writable
data home; `DATAFORGE_THEME_CONFIG` selects that copy and leaves packaged assets unchanged.
TOML Kit preserves custom TOML syntax/comments during updates (including multiline arrays):
[official API](https://tomlkit.readthedocs.io/en/latest/quickstart/).

## Maintenance and runtime configuration

`connections.py` owns `RuntimeConnections`, prefixed default provider key names and the
context-local injection scope. A manager belongs to one browser session, never a global
Streamlit cache. Pass secrets directly to adapters; do not mutate `os.environ` for session
credentials. The explicit profile variable name can resolve a legacy startup value read-only.
Only non-secret validated profile preferences persist; reject secret-bearing endpoints and
redact provider responses/errors before durable storage. Keep imported original evidence exact.

`cleanup.py` owns preview/apply and category dependencies; `database_maintenance.py` owns
integrity, snapshots and safe new-home restore. UI and `AgentService` delegate to these services.
New cleanup categories require fixed selectors, dependent-record handling, active-operation
guards, preview revalidation, scope permission and confirmation tests. Never add caller SQL or
arbitrary cleanup paths. Whole-home actions must reject workspace-limited authorization.
MCP cleanup tools remain read-only. Logical row estimates must not be described as disk savings.

Use isolated temporary homes for deletion/restore tests, including shared blobs across two
workspaces, retained history, expired preview, active jobs and redirected paths. General cleanup
does not acquire a journaled undo guarantee simply because the older history/staging helper does.
Opt-in expired staging cleanup runs when its UI page is visited, not in a background scheduler.
Migration versions remain 1–4 for this feature; never delete schema as ordinary runtime reset.

## Packaging and release checks

`launcher.py` resolves checkout/packaged UI assets; `build.py` exposes `dataforge-build`.
Include new UI/static/prompt resources in the wheel and frozen build, and verify imports plus
real startup outside the checkout. Source data belongs under the runtime home, not `_app`.
Frozen `--cli` forwards to existing CLI/MCP code. Keep default data homes and installed theme
copies compatible across upgrades.

Run `uv run dataforge-build --target python`, `--target docker` or `--target executable`.
Use `--target all` when all prerequisites exist. Run `uv run dataforge-build --verify`, then
smoke-test each artifact; checksum verification alone does not prove startup. Builds run on
their target OS for native bundles and receive no provider credentials from the parent
environment. Preserve the lock and version metadata, review output exclusions, record native
platform/remote CI limits, and update folder knowledge and implementation status.
