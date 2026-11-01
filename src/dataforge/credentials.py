"""Application-owned native credentials; no discovery, fallback or secret serialization."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import uuid
from pathlib import Path

SAVED_PREFIX = 'DATAFORGE_SAVED_'
SESSION_PREFIX = 'DATAFORGE_SESSION_'


class CredentialError(ValueError):
    """A safe user-facing credential failure, never a native exception payload."""


def credential_source(reference: str) -> str:
    """Reserved references select one source; legacy references select environment."""
    if reference.startswith(SAVED_PREFIX):
        return 'saved'
    if reference.startswith(SESSION_PREFIX):
        return 'session'
    return 'environment'


def credential_reference(home, workspace, profile_id, profile, *, saved=False) -> str:
    """Bind identity to the full authorized recipient, including path/auth/version."""
    identity = [str(Path(home).resolve()).casefold() if sys.platform == 'win32' else str(Path(home).resolve()),
                workspace, profile_id, profile.provider, profile.base_url, profile.auth, profile.api_version]
    digest = hashlib.sha256(json.dumps(identity).encode()).hexdigest().upper()
    return (SAVED_PREFIX if saved else SESSION_PREFIX) + digest


def owns_reference(home, workspace, profile_id, profile) -> bool:
    """Accept only an exact application-owned reference in this recipient scope."""
    expected = credential_reference(home, workspace, profile_id, profile, saved=True)
    return bool(re.fullmatch(re.escape(expected) + r'_[A-F0-9]{32}', profile.key_env))


def approved_backend():
    """Instantiate only a qualified native backend, ignoring keyring discovery/config."""
    try:
        if sys.platform != 'win32':
            raise CredentialError('Secure local storage is not verified on this OS; choose session-only storage.')
        from keyring.backends.Windows import WinVaultKeyring
        backend = WinVaultKeyring()
        backend.persist = 'local machine'
        if type(backend) is not WinVaultKeyring or backend.persist != 2 or backend.priority <= 0:
            raise CredentialError('Unapproved credential backend; choose session-only storage.')
        return backend
    except CredentialError:
        raise
    except Exception:
        raise CredentialError('Secure local storage is unavailable; choose session-only storage.') from None


class NativeCredentials:
    """Operate on exact owned entries only; callers authorize before reading."""

    @staticmethod
    def _service(reference):
        return 'GraveTrail/' + reference

    def save(self, home, workspace, profile_id, profile, secret):
        """Write a fresh entry; replacement never overwrites an existing native entry."""
        from dataforge.connections import _validate_credential
        reference = credential_reference(home, workspace, profile_id, profile, saved=True) + '_' + uuid.uuid4().hex.upper()
        _validate_credential(reference, secret)
        backend = approved_backend()
        try:
            backend.set_password(self._service(reference), 'api-key', secret)
        except Exception:
            try:
                backend.delete_password(self._service(reference), 'api-key')
            except Exception:
                raise CredentialError('Save failed and cleanup could not be confirmed. Remove the new GraveTrail entry '
                                      f'{reference} in OS credential settings; choose session-only storage.') from None
            raise CredentialError('Secure local save failed; choose session-only storage.') from None
        return reference

    def read(self, home, workspace, profile_id, profile):
        """Read only a bound reference, with no environment or fallback resolution."""
        if not owns_reference(home, workspace, profile_id, profile):
            raise CredentialError('Saved credential identity changed; explicitly rebind or save a new key.')
        try:
            return approved_backend().get_password(self._service(profile.key_env), 'api-key') or ''
        except CredentialError:
            raise
        except Exception:
            raise CredentialError('Secure local storage is locked or unavailable; unlock it or choose session-only storage.') from None

    def delete(self, home, workspace, profile_id, profile):
        """Delete an exact owned entry; missing entries are already deleted."""
        profile = profile.model_copy(update={'key_env': profile.saved_key_ref or profile.key_env})
        if credential_source(profile.key_env) != 'saved':
            return
        if not owns_reference(home, workspace, profile_id, profile):
            raise CredentialError('Saved credential identity changed; rebind before deleting through this profile.')
        from keyring.errors import PasswordDeleteError
        try:
            approved_backend().delete_password(self._service(profile.key_env), 'api-key')
        except PasswordDeleteError:
            pass
        except CredentialError:
            raise
        except Exception:
            raise CredentialError('Saved key deletion failed. The reference was retained; unlock storage and retry.') from None
