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

Do not put imported code, API keys, rendered trees or complete inventories in session state.
Use file IDs and lazy source retrieval. New graph code must preserve evidence and cap work on
cycles/dense graphs. New provider code must honor privacy before any network request.
