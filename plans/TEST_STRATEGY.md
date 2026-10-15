# Test strategy

Use deterministic unit fixtures for parser precision and negative cases; integration tests
exercise real DuckDB/filesystem ZIP-to-graph and restart workflows. Streamlit AppTest covers
page rendering, forms and navigation. Browser automation checks the actual running UI,
uploads where supported, graph interaction and source evidence. HTTPX MockTransport verifies
provider protocol/validation without credentials. Never claim this is a live provider test.
Run `uv run pytest`, `uv run ruff check .`, health endpoint and a generated workload benchmark.
Security gates: paths, symlinks, size/count/ratio limits, HTML escape, parameterized storage,
untrusted source never executed, secrets never exported, remote privacy blocked by default.
