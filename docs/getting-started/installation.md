# Install the documented version

The walkthroughs use development commit **313587e**. Use this checkout to
reproduce the controls shown in the screenshots.

## Recommended: locked source checkout

You need Python **3.11+**, Git and [uv](https://docs.astral.sh/uv/getting-started/installation/).
Initial setup normally downloads packages. No AI credentials or dbt installation are needed.

```sh
git clone https://github.com/SahasilAK/GraveTrail.git
cd GraveTrail
git checkout 313587e3217104dddc9e094a7a78cb79bf1ed64b
uv sync --locked --extra dev
uv run gravetrail-ui --home ./.dataforge
```

Open [http://127.0.0.1:8501](http://127.0.0.1:8501). Keep the terminal running.

This checkout adds `keyring>=25.7,<26` for optional **Remember on this device** API keys.
Locked Windows installs include `pywin32-ctypes` and keyring's `jaraco.*` dependencies.
The frozen build explicitly collects keyring and win32ctypes. Windows Credential Manager
uses current-user/local-machine persistence; macOS/Linux native stores remain disabled
until verified, including in headless/container installs. Session-only and environment
references still work without an available native store. See [secure configuration](../SECURE_CONFIGURATION.md).
The explicit home is persistent and Git-ignored; an absolute directory can keep data
outside the checkout. Pass the same home when switching to CLI/MCP. **Stop the UI with
Ctrl+C first:** one process owns each DuckDB home.

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
