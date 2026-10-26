# Install the documented version

These guides describe development commit **1864dc8**, 48 commits ahead of the local
`main` baseline when the overhaul began. dbt and the current independent AI workflow
postdate release **v0.0.1**. Use this checkout for demonstrated features.

## Recommended: locked source checkout

You need Python **3.11+**, Git and [uv](https://docs.astral.sh/uv/getting-started/installation/).
Initial setup normally downloads packages. No AI credentials or dbt installation are needed.

```sh
git clone https://github.com/SahasilAK/GraveTrail.git
cd GraveTrail
git checkout 1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414
uv sync --locked --extra dev
uv run gravetrail-ui --home ./.dataforge
```

Open [http://127.0.0.1:8501](http://127.0.0.1:8501). Keep the terminal running.
The explicit home is persistent and Git-ignored; an absolute directory can keep data
outside the checkout. Pass the same home when switching to CLI/MCP. **Stop the UI with
Ctrl+C first:** one process owns each DuckDB home.

The pin reproduces application behavior. This documentation overhaul remains on
`chore/documentation-overhaul` until review; contributors editing these pages should
use that branch rather than checking out the baseline over their changes.

## Choose another delivery method

| Method | Suitable when | Read first |
| --- | --- | --- |
| Source | Reproducing tutorials or contributing | Commands above; [configuration](configuration.md) |
| Wheel | Managed Python environment | [Pillow compatibility override](../SETUP_AND_DEPLOYMENT.md#temporary-pillow-security-compatibility) |
| Docker built from checkout | Isolated dependencies, persistent volume | [Setup reference](../SETUP_AND_DEPLOYMENT.md) |
| Native bundle/installer | Features in a particular released build | [Build/release and platform limits](../BUILD_AND_RELEASE.md) |

The lock carries a tested Streamlit/Pillow compatibility override. Plain pip resolution
does not reproduce it; use the wheel override command. Package version `0.1.0` alone
does not identify all behavior in this development checkout.

## Confirm the setup

```sh
uv run gravetrail-ui --help
uv run gravetrail --help
```

Continue with [your first lineage](quick-start.md). Port or home-lock errors?
See [troubleshooting](../troubleshooting/help.md).
