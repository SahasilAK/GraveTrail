# docs/assets/examples/

- `lineage.html` — self-contained application-generated graph for tracked tests/fixtures/scenario customer-summary pipeline (four assets/three relationships). Contains safe relative source evidence, inline CSS/JS and a network-blocking content policy. Embedded in a sandbox by examples/interactive-lineage.md; standalone download is a snapshot, not a workspace.

Authoring: scripts/docs/example.py uses an isolated Store with app dependencies, strips workspace metadata and prints SHA-256. Publication accepts only the exact reviewed path/digest in scripts/docs/hooks.py; arbitrary executable HTML remains forbidden. Served interaction/CSP proof differs from unverified browser offline-switch/local-file behavior.
