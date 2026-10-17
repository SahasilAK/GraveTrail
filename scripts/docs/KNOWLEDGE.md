# scripts/docs/

Static documentation tooling; application services unchanged.

## Files
- `hooks.py` — nav_documents/page_output/public_files and MkDocs on_files: public nav/assets only, unsafe/missing/symlink rejection, installed-theme retention, lowercase directory URLs.
- `build.py` — clean strict MkDocs build followed by exact output inspection; run from any directory.
- `validate.py` — inspect_site checks HTML anchors/resources/prefix and CSS URLs; inspect_inventory rejects missing/unexpected files/symlinks; validate checks search and repository references. CLI: python -m scripts.docs.validate.

Tests: tests/test_documentation.py. Install locked docs group; mkdocs.yml is authoritative. No runtime data or credentials required.
