# Extending GraveTrail

**Parsers:** add a module under `src/dataforge/parsers/` returning `ParseResult`, with
`Operation` inputs/outputs, exact code/line ranges, `Usage` direct references and `Diagnostic`
uncertainties. Add file extension routing in ingestion/services and UI filters. Never execute
imported content. Add positive and negative fixtures and bump `PARSER_VERSION`.

**dbt:** extend `dbt/` project/resource readers and the shared `DbtOperations` handlers.
Preserve exact logical identities, candidate versus resolved relationships, bounded static
analysis and source/generated evidence origins. Add schema fixtures before claiming another
artifact version or adapter; see [dbt support](DBT_SUPPORT.md).

**Providers:** add a validated provider identity/default URL and protocol branch in `Adapter`.
Test payloads, auth headers, discovery, retries and responses with HTTPX MockTransport. Honor
external/context/privacy gates and never persist a secret. Unsupported model capabilities must
be configurable, not silently assumed. Keep prompt/schema regressions synchronized.

**Pages/tools:** add a script under `ui/pages/`, register with `st.Page` in `app.py`, reuse
`ui.common` exact asset selection/source view/downloads. Keep business logic in services and
use existing facts. Test rendering/interactions with AppTest and custom JS in a real browser.

**Schema:** add a numbered, transactional, additive migration; never drop facts as a shortcut.
Back up a stopped runtime home before release. Derived tables are rebuilt atomically from
inventory; keep stable IDs and source-version evidence across interfaces.

**Exporters/graphs:** preserve all edge evidence when filtering/collapsing nodes. Bound fanout,
traversal, paths and HTML rendering. Reuse the offline renderer; render untrusted strings as
text and safely encode JSON. Any new scientific/performance claim needs a recorded workload.
