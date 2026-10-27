# docs/assets/

Public assets require individual mkdocs.yml extra.public_assets registration. The hook rejects unsafe paths/symlinks and arbitrary HTML; only the reviewed self-contained example is admitted by exact SHA-256. Maps and local proof/intermediate files are excluded.

- `images/` — supplied branding and real safe-fixture application/example captures; [map](images/KNOWLEDGE.md).
- `diagrams/` — accessible editable standalone lineage/context/request SVGs; core diagrams render without a CDN; [map](diagrams/KNOWLEDGE.md).
- `examples/` — reviewed inert-data interactive HTML snapshot with bounded inline script/CSP; [map](examples/KNOWLEDGE.md).
- `stylesheets/` — semantic theme, learning-path/cards and responsive demo styling; [map](stylesheets/KNOWLEDGE.md).
- `javascripts/` — native accessible persisted palette selection; [map](javascripts/KNOWLEDGE.md).
