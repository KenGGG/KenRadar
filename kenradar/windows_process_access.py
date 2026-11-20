"""Allow this Windows account to manage Radar across S4U/desktop logons."""
import os


def allow_account_control(pid=None):
    if os.name != 'nt':
        return
    import ctypes as c
    from ctypes import wintypes as w
    p = c.c_void_p
    class Trustee(c.Structure):
        _fields_ = [('multiple', p), ('operation', w.DWORD), ('form', w.DWORD),
                    ('kind', w.DWORD), ('name', p)]
    class Access(c.Structure):
        _fields_ = [('permissions', w.DWORD), ('mode', w.DWORD),
                    ('inheritance', w.DWORD), ('trustee', Trustee)]
    k = c.WinDLL('kernel32', use_last_error=True)
    a = c.WinDLL('advapi32', use_last_error=True)
    k.OpenProcess.argtypes, k.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
    k.GetCurrentProcess.restype = w.HANDLE
    k.CloseHandle.argtypes = [w.HANDLE]
    k.LocalFree.argtypes = [p]
    a.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)]
    a.GetTokenInformation.argtypes = [w.HANDLE, w.DWORD, p, w.DWORD, c.POINTER(w.DWORD)]
    a.GetSecurityInfo.argtypes = [w.HANDLE, w.DWORD, w.DWORD, p, p, c.POINTER(p), p, c.POINTER(p)]
    a.SetEntriesInAclW.argtypes = [w.ULONG, c.POINTER(Access), p, c.POINTER(p)]
    a.SetSecurityInfo.argtypes = [w.HANDLE, w.DWORD, w.DWORD, p, p, p, p]
    process = k.OpenProcess(0x60000, False, pid or os.getpid())  # READ_CONTROL | WRITE_DAC
    if not process:
        raise c.WinError(c.get_last_error())
    token, descriptor, acl, merged = w.HANDLE(), p(), p(), p()
    try:
        if not a.OpenProcessToken(k.GetCurrentProcess(), 8, c.byref(token)):
            raise c.WinError(c.get_last_error())
        size = w.DWORD()
        a.GetTokenInformation(token, 1, None, 0, c.byref(size))
        buffer = c.create_string_buffer(size.value)
        if not a.GetTokenInformation(token, 1, buffer, size, c.byref(size)):
            raise c.WinError(c.get_last_error())
        sid = c.cast(buffer, c.POINTER(p))[0]
        error = a.GetSecurityInfo(process, 6, 4, None, None, c.byref(acl), None, c.byref(descriptor))
        if error:
            raise c.WinError(error)
        # Query identity/cmdline, wait, terminate. No write-memory/injection or
        # permission-changing rights, and no Everyone/other-account grant.
        entry = Access(0x101411, 1, 0, Trustee(None, 0, 0, 1, sid))
        error = a.SetEntriesInAclW(1, c.byref(entry), acl, c.byref(merged))
        if error:
            raise c.WinError(error)
        error = a.SetSecurityInfo(process, 6, 4, None, None, merged, None)
        if error:
            raise c.WinError(error)
    finally:
        if merged: k.LocalFree(merged)
        if descriptor: k.LocalFree(descriptor)
        if token: k.CloseHandle(token)
        k.CloseHandle(process)
