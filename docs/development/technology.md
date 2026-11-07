# Technologies and why they are here

This is the stack declared by [pyproject.toml](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/pyproject.toml) and used by the pinned source.
Version ranges below describe repository constraints; they are not claims about the latest
upstream release. Use `uv.lock` for resolved versions and keep lock updates explicit.

## Runtime

| Technology | Declared constraint | Actual use and boundary | First implementation to read |
| --- | --- | --- | --- |
| Python | >=3.11 | application, static analysis, local jobs and build scripts | [project scripts](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/pyproject.toml) |
| Streamlit | ==1.66.0 | reactive UI, navigation, AppTest and custom components; no domain ownership | [app](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/app.py), [UI common](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/ui/common.py) |
| DuckDB | >=1.5,<2 | embedded local metadata/facts database; imported SQL is never submitted as executable SQL | [Store](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/store.py) |
| SQLGlot | >=30.23,<31 | SQL ASTs, scopes, dialects, typed DDL, static SAS SQL and legacy/focused grounding helpers; current independent AI extraction does not invoke static semantic approval | [SQL parser](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/parsers/sql.py), [dbt analysis](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/dbt/analysis.py) |
| NetworkX | >=3.4,<4 | directed graph traversal, cycles, temporary contraction and AI operation/composition graph checks | [graph](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/graph.py), [AI linking](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/ai_linking.py) |
| Pydantic | >=2.11,<3 | strict request/settings/provider/schema validation; model output still requires host grounding | [configuration](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/configuration.py), [analysis models](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/ai_analysis_models.py) |
| charset-normalizer | >=3.4,<4 | bounded text decoding with diagnostics when encoding is detected | [ingestion](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/ingestion.py) |
| HTTPX | >=0.28,<1 | provider HTTP transport; protocols tested with `MockTransport` | [LLM adapter](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/llm.py) |
| Typer | >=0.16,<1 | console command parsing and help; calls shared `AgentService` | [CLI](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/cli.py) |
| MCP SDK | >=1.26,<2 | typed tools/resources/prompts, stdio and guarded Streamable HTTP | [MCP server](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/agent/mcp_server.py) |
| tomlkit | >=0.13,<1 | bounded, atomic theme configuration changes while preserving TOML structure | [UI themes](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/ui/themes.py), [theme service](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/theme_configuration.py) |
| XlsxWriter | >=3.2.9,<4 | bounded constant-memory, literal-text XLSX reports | [Excel export](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/excel_exports.py) |
| resvg-py | >=0.5,<0.6 | optional-at-runtime PNG rasterization in bounded subprocess workers | [graph images](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/graph_images.py), [worker](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/image_worker.py) |
| Pillow | ==13.0.0 | UI/image compatibility and packaging; see the tested Streamlit metadata override | [Pillow regression](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_pillow_compatibility.py), [security policy](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/SECURITY.md) |
| PyYAML | >=6.0.3,<7 | bounded safe dbt YAML parsing, duplicate/tag/cycle/depth rejection | [dbt YAML](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/dbt/yaml.py) |
| Jinja2 | >=3.1.6,<4 | parse static dbt templates and calls; imported templates are never rendered or evaluated | [dbt templates](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/dbt/templates.py) |
| tiktoken (extra) | >=0.12,<1 | optional offline tokenizer with a pinned bundled encoding; conservative fallback remains available | [AI budget](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/ai_budget.py) |

`ai-tokenizers` is an optional dependency extra. `resvg-py` is declared as a runtime dependency,
but renderer discovery handles import failure and can still offer SVG. These are different
forms of optionality. The Streamlit/Pillow metadata exception is duplicated deliberately in
`tool.uv.override-dependencies` and [dependency-overrides.txt](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/dependency-overrides.txt);
review [SECURITY.md](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/SECURITY.md) before changing it.

## Development, documentation and distribution

| Tool | Repository use | Verification boundary |
| --- | --- | --- |
| uv | locked environment and dependency-group synchronization | installation success does not prove application behavior |
| pytest >=8,<10 | unit, persisted workflow, AppTest, protocol and regression tests | mocks do not establish live provider availability; AppTest does not run browser JS |
| Ruff >=0.14,<1 | import ordering and selected E/F/I lint rules, Python 3.11 target | lint does not validate lineage semantics |
| Hatchling | wheel/sdist backend; custom hook bundles app, UI, prompts and theme assets | test an installed wheel outside the source checkout |
| PyInstaller >=6.22,<7 | host-platform standalone bundle | native builds need target-platform smoke tests |
| MkDocs 1.6.1, Material 9.7.7, pymdown-extensions 12.3 | docs dependency group, strict static site and publication artifact | run the repository builder/validator, then inspect published artifact for hosting claims |
| Docker | reproducible container packaging and smoke checks | image build success alone is not a successful deployment |
| GitHub Actions | Ubuntu/Windows Python 3.12 tests, security, docs, release and artifact publication | inspect each workflow's actual triggers and permissions |
| Node.js 24 in test CI | browser JavaScript checks invoked by the Python suite | it is test tooling, not the application's backend runtime |

Read [tests workflow](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/.github/workflows/tests.yml), [docs workflow](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/.github/workflows/docs.yml),
[release workflow](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/.github/workflows/release.yml), [build module](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/build.py) and
[asset hook](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/scripts/build/hatch_assets.py) before changing tooling. Installer signing,
frozen process ownership and Windows replacement checks live under `scripts/build/`.

## What this architecture does not require

Core analysis uses retained text and local facts. It does not need a remote database,
licensed SAS runtime, dbt invocation or a JavaScript frontend build pipeline. Provider calls
are explicit opt-in requests through HTTPX. Jinja parsing does not grant template execution;
Python dbt resources are inspected rather than imported. Those boundaries explain why
adding an execution engine is a product/security change, not a new parser branch.
