"""One bridge per user owns hardware, regardless of HTTP port or data directory."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import stat


class HardwareOwner:
    def __init__(self):
        self.handle = None
        self.descriptor = None
        if os.name != "nt":
            import fcntl
            directory = Path.home() / ".keyphore-keydous"
            directory.mkdir(mode=0o700, exist_ok=True)
            info = directory.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                raise OSError("硬件锁目录必须属于当前用户且不能为链接")
            descriptor = os.open(directory / "hardware-owner.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                info = os.fstat(descriptor)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                    raise OSError("硬件锁文件无效")
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (OSError, ValueError):
                os.close(descriptor)
                raise OSError("Keyphore · Keydous 已在运行或无法取得硬件锁") from None
            self.descriptor = descriptor
            return
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        api.CreateMutexW.restype = wintypes.HANDLE
        api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        api.WaitForSingleObject.restype = wintypes.DWORD
        api.ReleaseMutex.argtypes = [wintypes.HANDLE]
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api = api
        handle = api.CreateMutexW(None, False, "Local\\Keyphore-Keydous-HardwareOwner-v1")
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        result = api.WaitForSingleObject(handle, 0)
        if result not in (0, 0x80):
            api.CloseHandle(handle)
            raise OSError("Keyphore · Keydous 已在运行，请使用已有页面。不同端口也不能同时控制键盘。")
        self.handle = handle

    def close(self):
        if self.descriptor is not None:
            os.close(self.descriptor)  # Keep inode stable; unlink would permit two owners.
            self.descriptor = None
        if self.handle:
            self.api.ReleaseMutex(self.handle)
            self.api.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
