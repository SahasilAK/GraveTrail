# Secure local credentials implementation plan

Goal: implement the user's session-default, explicit opt-in native storage requirements on chore/audit-realted-cleanup without touching existing work or publishing.

Architecture: reserve opaque DATAFORGE_SESSION_ and DATAFORGE_SAVED_ references in the existing Profile.key_env field. Derive scope from canonical data home, workspace, profile ID and recipient configuration. RuntimeConnections remains request/context scoped; launch policy still authorizes exact references before vault reads. Legacy environment references retain their behavior. Only the verified Windows WinVaultKeyring implementation is approved; explicitly force local-machine persistence. Other platforms fail closed pending native qualification.

- [x] Write fake-backend tests for scope/source isolation, lifecycle failures, redaction and agent grants; observe failure.
- [x] Add native store adapter and scoped RuntimeConnections, retaining profile fingerprint invalidation.
- [x] Integrate provider requests, UI actions, background jobs, profile/workspace deletion and restore invalidation.
- [x] Add UI, durable artifact, packaging and authorization regressions.
- [x] Update security, configuration, installation and affected knowledge maps.
- [x] Run focused regressions, lint, full suite, wheel/frozen checks and disposable native Windows round trip. Report exact qualification limits.

Review focus: no implicit fallback; endpoint edits never reuse saved keys; settings rendering never decrypts; failed deletion retains the reference for retry; failed save cleans only its newly created entry; restore requires rebinding; agents cannot save raw keys or self-grant access. Session disconnect must suppress saved retrieval until explicitly reconnected, and never delete the saved entry.

Implementation rulings: keep Profile.key_env as the selected reference, with saved_key_ref as optional non-secret standby metadata, so session-only selection cannot overwrite or implicitly delete a saved key. Only Windows is approved; unqualified macOS/Linux native storage fails closed. Source changes update only references, never persist entered session values. Restore clears saved bindings even when files later move to their old path. Native/DB updates cannot be jointly atomic; transactional SQL errors preserve the old key, native delete failures roll SQL back, failed new saves clean their own entry, and crash/commit failures may need explicit recovery.

Independent review found and verified fixes for request redaction after saved runtime connection, disconnect surviving fingerprint edits, replacement SQL failure cleanup, new-profile ID reuse and saved reconnect source selection. Final review: no remaining important findings; independent credential suite 14 passed. First full run: 1285 passed, 3 skipped, one stale generated inventory failure; inventory regenerated before the final full run.

Final boundary regression: a hidden session override invalidated by request-option edits must leave the unchanged selected reference disconnected, never fall through to the saved key. Observed the new assertion fail, added the invalidation tombstone and verified 60 focused provider/connection/AI/UI tests pass. The acceptance full suite and artifact rebuild include this fix.

Native qualification: disposable Windows entries only, current-user Persist=2, new manager and subprocess retrieval, installed-wheel/frozen CLI authentication to a temporary local HTTP server, and deletion/absence checks. No existing vault entries read or enumerated. Real locked-vault, reboot and domain-roaming behavior not exercised. Build dependency/backend contents and CLI startup verified. Final verification results recorded below after completion.

Final acceptance: 1288 passed, 3 skipped in 617.37 seconds; skips require Node.js or Windows symlink privileges. Focused provider/connection/AI/UI regressions: 60 passed. Ruff and git diff --check clean; source inventory current; strict MkDocs build passed. Four rebuilt wheel/source/override/frozen artifacts have verified checksums; wheel implementation/UI bytes match the reviewed source, frozen native dependency modules are present, and frozen CLI startup passes. No push, publication, merge or commit was performed. Real native and mocked failure qualifications remain distinct as recorded in BUILD_AND_RELEASE.md.
