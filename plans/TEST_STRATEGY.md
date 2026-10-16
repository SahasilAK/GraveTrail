# Test strategy

Use deterministic unit fixtures for parser precision and negative cases; integration tests
exercise real DuckDB/filesystem ZIP-to-graph and restart workflows. Streamlit AppTest covers
page rendering, forms and navigation. Browser automation checks the actual running UI,
uploads where supported, graph interaction and source evidence. HTTPX MockTransport verifies
provider protocol/validation without credentials. Never claim this is a live provider test.
Run `uv run pytest`, `uv run ruff check .`, health endpoint and a generated workload benchmark.
Security gates: paths, symlinks, size/count/ratio limits, HTML escape, parameterized storage,
untrusted source never executed, secrets never exported, remote privacy blocked by default.


## Agent integration

`uv run pytest tests/test_agent_service.py tests/test_agent_cli.py tests/test_agent_mcp.py
tests/test_agent_settings.py -q` covers SQL/SAS/CSV stored-query parity, source disclosure,
ambiguity/freshness, paging/budgets, jobs, workspace access, CLI background workflows, actual
SDK stdio/HTTP and AppTest settings. Run the full suite to preserve existing functionality.
`scripts/verify_agents.py` additionally imports both user-supplied ZIPs in an isolated home,
compares manifests and measures responses. It reports existing SAS FORMAT-modifier gaps.
Real UI testing checks Settings agent controls/tool discovery/local handler success.
