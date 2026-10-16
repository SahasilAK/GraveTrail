# Agent integration acceptance — 2026-10-16

Specification: `docs/prompts/FEATURE_AGENT_INTEGRATION.md`. Implemented additively;
optional REST omitted because CLI/MCP cover the requested workflows.

| Requirement | Verification |
| --- | --- |
| CLI without Streamlit | Subprocess help/workspace/import/build/export; isolated installed wheel imports CLI/MCP with Streamlit absent from `sys.modules` |
| MCP without Streamlit | Real SDK stdio subprocess initializes and queries; independent HTTP startup |
| CLI/MCP consistent lineage | Both delegate to AgentService; SDK response equals the same real-store service query, CLI resolves actual imported/built lineage |
| Stored metadata/cache reuse | Query test refuses analysis calls; both supplied ZIP warm refreshes reuse all 86 cached scripts |
| Smaller summary defaults | SQL 1,509 vs 64,841 chars; SAS 1,509 vs 45,454 chars, both pub.all_kpis |
| Pagination/output budgets | Query-bound cursors, max chars/items/depth, aggregate batch budgets and explicit oversized-record errors |
| Source only on request | Summary/search omit code; explicit lines/statement/operation retrieval; standard columns omit expressions; revocation enforced |
| Ambiguous names | Candidate asset IDs returned; no arbitrary first match |
| Usable long jobs | Persistent journal/results, detached CLI build, heartbeat/interruption, progress adapter, nonblocking MCP status |
| Unauthorized mutations rejected | Startup read-only and per-workspace write/source/access gates tested |
| Workspace boundaries | Cross-workspace file/job IDs and restricted workspace listing rejected/filtered; scoped cursors |
| Secured network transport | Missing/short token or workspace scope refused; unauthenticated GET/POST/DELETE 401; authenticated SDK HTTP initialize/query succeeds |
| No LLM in normal queries | Existing deterministic services only; query tests fail network connection attempts/reanalysis |
| Streamlit preserved | Full existing suite; agent Settings AppTest; actual running app renders controls and successful local MCP handler result |
| Meaningful failures | Structured CLI exits, MCP isError, invalid IDs/cursors/ranges, job errors/restart states, import-root and response-budget refusal |

## Recorded checks

- Full `uv run pytest -q`: **242 passed, 1 existing skipped**, 43.81 seconds.
- Focused agent tests: **18 passed**. Ruff and `uv lock --check` pass.
- Wheel and sdist built. Isolated wheel installation imports from site-packages;
  CLI/MCP imports do not load Streamlit. Packaged console entry point exists.
- Actual running app at loopback 8505 uses an isolated sample home; primary 8501
  runtime data/theme preserved. Settings displays workspace permission controls,
  valid Codex/Claude configuration examples, discovered tools and successful MCP
  handler counts (86 files / 92 registry assets / 128 evidence edges).
- Independent reviewer verified real authenticated HTTP in a subprocess and flagged
  import callback, standard-column disclosure, CLI polling authorization/budgets and
  MCP polling blockage. All have regression coverage and fixes. Additional full-suite
  startup race was fixed with bounded detached-worker ownership retries. Async MCP
  wrappers prevent another waiting query from blocking status delivery.

## Fixture observations and boundaries

- Fresh SQL fixture: 86 scripts analyzed, all 128 logical/evidence edges match the
  manifest, no extras/missing edges, all 16 sources reached through seven layers,
  81 dependencies upstream of pub.all_kpis. Registry has 92 assets including seven
  isolated setup/schema names in addition to the manifest's 85 persistent tables.
- SAS parser8 follow-up: 86 scripts analyzed, 101 assets including 16 WORK assets,
  144 physical/128 collapsed logical edges exactly matching the manifest; pub.all_kpis
  reaches all16 sources through seven layers. All86 warm parses are cached. The31
  diagnostics comprise eight setup macro warnings and23 informational library/inline-data
  notices, with no parse errors. Earlier FORMAT= failures are resolved by the parser fix.
- Token estimates are ceil(characters/4), not billing tokens. Fixture verification
  executes no SQL/SAS. Full DuckDB transformation and licensed SAS execution remain
  unverified as previously recorded by the user.
- DuckDB ownership is one process per home. MCP requests share an owning process;
  separate UI/CLI processes must release ownership or use separate homes. Busy is
  explicit. Remote TLS deployment and installation into actual Codex/Claude client
  configurations were not performed. Examples were checked against official docs.
- Private pre-provisioned HTTP bearer credentials are supported; OAuth discovery,
  multi-user identity, REST and distributed infrastructure are intentionally absent.

Raw test/sample/build artifacts are under `.dataforge/verification/`; reproduce
sample measurements with `scripts/verify_agents.py` and an isolated runtime home.
