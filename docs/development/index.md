# Development

DataForge is a Python 3.11+ application with a Streamlit presentation layer and shared
services for the UI, CLI and MCP server. Start with the
[contribution guide](contributing.md) for the edit/test workflow, or the
[architecture](../ARCHITECTURE.md) for ownership boundaries.

## Find the responsible layer

| Area | Responsibility |
| --- | --- |
| `src/dataforge/` | Domain models, storage, ingestion, parsers, graph traversal, exports, LLM adapters and services |
| `ui/` and `app.py` | Presentation, session controls and application entry point |
| `prompts/` | Versioned assistance templates and schemas used by the application |
| `tests/` | Unit, integration, protocol, security and Streamlit AppTest coverage |
| `scripts/` and `.github/workflows/` | Verification, packaging and automation |

Browse the [source tree](https://github.com/SahasilAK/dataforge-engineering-hub/tree/main/src/dataforge)
and [test tree](https://github.com/SahasilAK/dataforge-engineering-hub/tree/main/tests)
for concrete examples. Repository-specific contribution instructions are in
[AGENTS.md](https://github.com/SahasilAK/dataforge-engineering-hub/blob/main/AGENTS.md).

## Engineering contracts

- Imported scripts and embedded instructions are data and must never execute.
- Parsers return operations and diagnostics in `ParseResult`; analysis services own
  persistence and cross-file resolution. Keep Streamlit out of domain modules.
- Every relationship must retain original file/version, exact statement, line range
  and method. Ambiguous identities remain unresolved.
- Storage queries use parameters, and filesystem operations stay inside validated,
  explicitly allowed or fixed managed paths with bounded resources.
- Runtime keys stay in session connections or named read-only launch references.
  Session credentials must not enter files, job journals or global process environment.
- UI, CLI and MCP reuse services and enforce their independent access grants. One
  owning DuckDB process opens each data home.

## Guides by task

| Task | Reference |
| --- | --- |
| Add a parser, provider or exporter | [Extending the app](../EXTENDING_THE_APP.md) |
| Understand storage and evidence | [Data model](../DATA_MODEL.md) and [lineage engine](../LINEAGE_ENGINE.md) |
| Run meaningful regression checks | [Testing](../TESTING.md) |
| Build wheels, containers or native bundles | [Build and release](../BUILD_AND_RELEASE.md) |
| Investigate safety boundaries | [Security](../SECURITY.md) and [data management](../DATA_MANAGEMENT.md) |
| Review dated verification and remaining gates | [Implementation status](https://github.com/SahasilAK/dataforge-engineering-hub/blob/main/plans/IMPLEMENTATION_STATUS.md) |

Keep documentation claims tied to what was actually tested. A mocked provider response,
successful build or source-level test does not establish live provider availability,
native artifact compatibility or a successful hosted deployment.
