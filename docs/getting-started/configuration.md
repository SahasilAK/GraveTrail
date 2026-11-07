# Configuration

GraveTrail separates startup configuration, workspace preferences and runtime secrets.
Choose storage and filesystem access before launching; tune analysis and display in
**Workspace settings** and the other Administration destinations after selecting a workspace.

## Storage and ownership

Use an explicit home when moving between source, installed and packaged launchers:

```sh
uv run gravetrail-ui --home /absolute/path/to/dataforge-data
uv run gravetrail --home /absolute/path/to/dataforge-data --json workspace list
```

Run these commands sequentially, stopping the UI before opening the home through an
independent CLI/MCP process. One DuckDB process owns each home. Separate homes are
independent databases and do not synchronize.

`--home` overrides `DATAFORGE_HOME`. Without either, a source checkout uses
`.dataforge/` in the working directory; an installed/frozen application uses the
platform's per-user data directory. Docker uses `/data`. See the complete
[default-home table](../SETUP_AND_DEPLOYMENT.md#11-data-storage-and-backup).

The home contains DuckDB metadata, immutable source blobs, retained history and
managed runtime files. Preserve the entire home in a backup rather than copying
an actively owned database. Restore whole-home backups into a new directory.

## Startup settings

| Setting | Purpose |
| --- | --- |
| `DATAFORGE_HOME` | Default persistent data home when `--home` is absent |
| `DATAFORGE_ALLOWED_ROOTS` | Explicit host directories permitted for server-side imports |
| `DATAFORGE_STORAGE_LOCATIONS` | Additional absolute homes offered by the UI storage selector |
| `--address`, `--port` on `gravetrail-ui` | Bind address and port; default `127.0.0.1:8501` |

Root/location lists use `;` on Windows and `:` on Linux/macOS. Additional storage
locations are capped at eight total including the default home. Opening another
location changes the current browser session's database; it does not migrate files.
Restart to change the startup allowlist.

The CLI supports repeatable `--allowed-root` and `--allowed-workspace` options.
Read-only access is the default, and no CLI import roots are implicitly granted.
Use the [CLI guide](../CLI_GUIDE.md) and [MCP guide](../MCP_INTEGRATION.md) for their
independent write, source, network and configuration grants.

## Workspace preferences

Use the focused administration destinations:

- **Workspace settings → Parsing:** dialect/folder/extension overrides, SAS mappings,
  job/session identities and case handling. **Resources** sets import/worker budgets;
  **Appearance** sets graph/source defaults and all eighteen theme presets.
- **Connections & AI:** provider profiles, session credentials, routing and Privacy.
- **Data management:** workspace details, configuration transfers, backup/restore,
  cleanup previews, history recovery and permitted storage locations.
- **Automation & access:** workspace access, source disclosure and response budgets.

Reanalyze after changing extraction-related settings. Normal analysis reuses compatible
unchanged parses; **Rebuild** forces parsing. Imported pending files are not automatically
evidence for the previous graph.

Configuration export/import transfers validated non-secret parsing, resource and graph
preferences into a new workspace. It excludes sources, history, credentials, provider
profiles and privacy permissions. Use a runtime backup when you need recovery of actual data.

## Optional LLM assistance

Deterministic analysis works with no provider profile. To enable assistance, choose a
provider, endpoint, model and authentication method in **Connections & AI → Providers & routing**.
Choose **This session only** (default), **Remember on this device** (explicit encrypted native
storage), or **Environment reference (advanced)**. Save a profile before saving its key.
Saving a profile stores non-secret preferences and the reference name, never the key value.
New credential reference names use the `DATAFORGE_` prefix; explicitly configured legacy
launch references remain compatible and read-only.

Session credentials need re-entry after restart. Browser disconnection does not guarantee
immediate or forensic memory erasure. Saved keys remain until deleted; Windows Credential
Manager is qualified with current-user/local-machine persistence. macOS/Linux persistence
is disabled pending native verification; use session storage there. Settings never decrypt
keys just to show status. Disconnect disables the selected credential in this session;
delete removes the saved key locally without revoking it at the provider. Legacy environment
profiles remain compatible and are never automatically imported into persistent storage.
Do not put key values in commands, committed files, provider URLs or exported configurations.

Requests require explicit action and the applicable privacy permissions. A loopback
gateway may forward code to a remote service. Review its recipient policy and send the
smallest useful source range. See [secure runtime configuration](../SECURE_CONFIGURATION.md),
[LLM integration](../LLM_INTEGRATION.md) and [security](../SECURITY.md).

## Maintenance settings

Use **Data management → Cleanup & recovery** to preview the exact records and files
affected by a cleanup. General cleanup requires a whole-home backup and typed confirmation;
changed previews must be refreshed. Source or AI cleanup invalidates the complete dependent
workspace graph. Shared cache/orphan/application cleanup is UI-only, and MCP cleanup is
read-only. Read the [data management guide](../DATA_MANAGEMENT.md) before applying changes.

See [GraveTrail rebrand compatibility](../BUILD_AND_RELEASE.md#gravetrail-rebrand-compatibility) for retained commands, environment variables and storage names.
