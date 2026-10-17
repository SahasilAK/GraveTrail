# Run and publish

Choose how to run the application separately from how to publish its documentation.
GitHub Pages serves static documentation; the Python application needs its own process
and persistent data home.

| Option | What it runs | Start here |
| --- | --- | --- |
| Source + uv or pip | UI, CLI and MCP from the checkout | [Setup and deployment](../SETUP_AND_DEPLOYMENT.md) |
| Python wheel | Packaged launchers and application assets | [Wheel installation](../SETUP_AND_DEPLOYMENT.md#4-python-installation) |
| Docker | Linux container with a persistent `/data` volume | [Container setup](../SETUP_AND_DEPLOYMENT.md#5-docker-installation) |
| Standalone bundle | Host-native directory distribution | [Build and release](../BUILD_AND_RELEASE.md) |
| GitHub Pages | Searchable public documentation only | [Publish the documentation](github-pages.md) |

Source version `0.1.0` is package metadata, not a claim of a published release. Build
artifacts must be verified outside the checkout; native executables need target-platform
testing. The [build guide](../BUILD_AND_RELEASE.md) records dated evidence and remaining gates.

## Before operating a data home

Use an explicit `--home` when switching between launchers. One process owns each DuckDB
home. The UI binds to loopback by default and is intended for one trusted local user.
Externally bound MCP HTTP needs authentication, workspace scope and a TLS reverse proxy;
it does not add multi-user authentication to the Streamlit application.

Supply credentials at runtime. Keep originals, databases, exports and backups out of
source control and static hosting. General cleanup requires a successful full-home backup;
restore archives into a new destination. See [data management](../DATA_MANAGEMENT.md) and
[security](../SECURITY.md) before cleanup, upgrades or recovery.
