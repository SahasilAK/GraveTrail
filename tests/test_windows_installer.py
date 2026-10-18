"""Installer safety and the frozen runtime's upgrade exclusion contract."""
import ctypes
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows named mutex API")
def test_windows_instance_mutex_exists_only_while_runtime_is_alive():
    from dataforge.launcher import windows_instance

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenMutexW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
    kernel.OpenMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    with windows_instance():
        handle = kernel.OpenMutexW(0x00100000, False, "Local\\GraveTrail.Application")
        assert handle
        kernel.CloseHandle(handle)
    assert not kernel.OpenMutexW(0x00100000, False, "Local\\GraveTrail.Application")


def test_installer_is_per_user_preserves_data_and_never_closes_live_owners():
    root = Path(__file__).resolve().parents[1]
    template = (root / "scripts/build/windows.iss").read_text()
    for required in ("PrivilegesRequired=lowest", "{localappdata}\\Programs\\GraveTrail",
                     "AppMutex=Local\\GraveTrail.Application", "CloseApplications=no",
                     "RestartApplications=no", "recursesubdirs"):
        assert required in template
    assert "[UninstallDelete]" not in template
    assert "taskkill" not in template.lower()
    assert "DataForge" not in template


def test_production_signing_requires_identity_and_checks_timestamp():
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts/build/sign_windows.ps1").read_text()
    for required in ("WINDOWS_SIGNING_THUMBPRINT", "TimeStamperCertificate", "Get-AuthenticodeSignature",
                     "'/fd' 'SHA256'", "'/td' 'SHA256'", "'/pa' '/all'", "VerifyOnly"):
        assert required in script
