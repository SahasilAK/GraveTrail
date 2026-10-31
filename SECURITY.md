# Security

GraveTrail is a local, single-user static-analysis tool. Keep the UI bound to loopback
and protect data homes, exports and backups: they can contain complete source code.
Read the [security and privacy guide](docs/SECURITY.md) for the implemented threat
boundaries, credential lifecycle, import protections and deployment requirements.

Optional saved API keys use the Python `keyring` library with an explicitly selected native
backend. Windows credentials are forced to current-user/local-machine persistence; other OS
backends remain disabled pending qualification. There is no independent master-password lock
or guarantee against malware running as the same user. See [secure configuration](docs/SECURE_CONFIGURATION.md)
for source selection, launch grants, deletion, restore and failure handling. Deleting local
storage does not revoke a provider key.

## Report a vulnerability

Do not post credentials, private source, live databases, backups or sensitive exploit
details in public issues or pull requests.

If this repository has GitHub private vulnerability reporting enabled, use **Security →
Report a vulnerability** to submit a private advisory. Availability depends on the
repository settings; this document does not establish a separate private reporting
endpoint or response-time commitment.

If that option is unavailable, open a public issue containing only a general request
for a private reporting channel. Wait for a maintainer to provide one before sharing
sensitive details. Include a minimal sanitized reproduction, affected revision/install
method, impact and relevant platform information through the agreed channel.

If a credential has already been exposed, revoke or rotate it with its provider.
Removing a key from a message or a saved profile does not revoke the credential or
remove existing copies of imported originals and backups.

## Automated checks and repository settings

The `security` workflow scans reachable Git history and the current tracked tree,
including nested ZIP fixtures, with checksum-pinned Gitleaks. Only exact dummy
redaction-test credentials in `tests/test_connections.py` are exempted. Findings
are redacted in CI logs. It also audits all locked dependency groups and extras
with pip-audit on Windows/Linux and Python 3.11/3.12. Both scans run on pushes,
pull requests, weekly schedules and manual dispatch; findings fail the job.
Scheduled runs use the default branch, so they begin after the workflow is merged.
The wheel audit runs the repository build hook, installs a clean wheel with the explicit compatibility policy and audits the installed third-party packages. Imported SQL/SAS is never executed by these scan jobs.

GitHub settings are separate from workflow files. Dependabot alerts were verified
enabled with no open alerts on 2026-10-17. While the repository was private, GitHub
reported secret scanning unavailable and returned 404 for private vulnerability
reporting. After making the repository public, an administrator should enable
private vulnerability reporting and verify secret scanning and push protection
under **Settings → Advanced Security**. These checks do not change visibility or
activate paid security products. This dated status is not a continuing assurance
that no alerts exist.

## Scope and updates

Reports about source ingestion, path/resource boundaries, evidence exports, credentials,
cleanup/restore and CLI/MCP authorization are relevant. This repository does not publish
a supported-version matrix or guaranteed security maintenance period. Include the exact
revision or package version you tested; verify fixes on the intended target platform.

On 2026-10-25, the locked build extra's setuptools was updated from 84.0.0 to
84.1.0 for [GHSA-xmj3-9gf7-h52w](https://github.com/pypa/setuptools/security/advisories/GHSA-xmj3-9gf7-h52w).
The complete locked-dependency and clean installed-wheel audits remain enabled;
no advisory is ignored. This is a build-tool lock update, not a runtime dependency
or data-format change.

## Temporary Streamlit/Pillow compatibility exception

The source lock and installers use exact **Streamlit 1.66.0 / Pillow 13.0.0** pins. Pillow 13 fixes the reported advisories; Streamlit 1.66's metadata still caps Pillow below 13. The only override is `pillow==13.0.0`, declared in `pyproject.toml` and the companion `dependency-overrides.txt`. Pin parity, the sole expected metadata discrepancy, image modes/resizing, public Streamlit image rendering and distribution boundaries are tested. This does not claim upstream support or universal compatibility.

`uv sync --locked` applies the checkout policy. Wheel users must explicitly supply the companion file with `uv pip install --overrides`; plain pip fails resolution instead of silently selecting vulnerable Pillow. Docker/native builds share the lock, and CI audits both every locked group and the actual clean-wheel environment on Windows/Linux Python 3.11/3.12. No advisory is ignored or audit disabled. Standard `pip check` reports the documented upstream metadata discrepancy; tests reject any additional discrepancy.

Removal requires an official stable Streamlit version supporting a patched Pillow, updated runtime requirements, removal of both temporary overrides, a regenerated lock, and passing UI/image/export/full-suite, installed-wheel and cross-platform audit checks. Installation commands and rollback implications are in the [installation guide](docs/SETUP_AND_DEPLOYMENT.md#temporary-pillow-security-compatibility). No user data migration is involved.
