"""Installer safety and the frozen runtime's upgrade exclusion contract."""
import ctypes
import sys

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows named mutex API")
def test_windows_instance_mutex_exists_only_while_runtime_is_alive() -> None:
    """Verify that windows instance mutex exists only while runtime is alive."""
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
