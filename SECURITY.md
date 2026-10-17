# Security

DataForge is a local, single-user static-analysis tool. Keep the UI bound to loopback
and protect data homes, exports and backups: they can contain complete source code.
Read the [security and privacy guide](docs/SECURITY.md) for the implemented threat
boundaries, credential lifecycle, import protections and deployment requirements.

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
No project code or imported SQL/SAS is executed by these scan jobs.

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
