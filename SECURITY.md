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

## Scope and updates

Reports about source ingestion, path/resource boundaries, evidence exports, credentials,
cleanup/restore and CLI/MCP authorization are relevant. This repository does not publish
a supported-version matrix or guaranteed security maintenance period. Include the exact
revision or package version you tested; verify fixes on the intended target platform.
