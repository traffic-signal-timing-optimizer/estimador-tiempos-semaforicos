"""Medidas del equipo y de un proceso hijo (DEV07 F2, decisiones D6 y D19).

Sin dependencias nuevas: en Windows se usa ``ctypes`` con la API del sistema; en Linux, ``/proc``.
En cualquier otro sistema las medidas de memoria devuelven ``None`` y la comprobación que las
usa se omite (el espacio en disco sí se mide en todos).
"""

import ctypes
import shutil
import sys
from pathlib import Path

__all__ = [
    "MemoryProbe",
    "available_memory_bytes",
    "free_disk_bytes",
    "kib_field",
    "total_memory_bytes",
]

# PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
_WINDOWS_ACCESS = 0x0400 | 0x0010
_KIB = 1024


def free_disk_bytes(path: Path) -> int:
    """Espacio libre en la unidad de ``path`` (o del ancestro más cercano que exista)."""
    probe = path.resolve()
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def kib_field(text: str, name: str) -> int | None:
    """Valor en bytes de la línea ``name:  <n> kB`` de un archivo de ``/proc``."""
    for line in text.splitlines():
        if line.startswith(f"{name}:"):
            _, _, rest = line.partition(":")
            digits = rest.split()[0] if rest.split() else ""
            if digits.isdigit():
                return int(digits) * _KIB
    return None


if sys.platform == "win32":
    from ctypes import wintypes

    class _MemoryStatus(ctypes.Structure):
        _fields_ = (
            ("dwLength", wintypes.DWORD),
            ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        )

    class _ProcessMemory(ctypes.Structure):
        _fields_ = (
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        )

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _psapi = ctypes.WinDLL("psapi", use_last_error=True)
    _kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.GlobalMemoryStatusEx.argtypes = (ctypes.POINTER(_MemoryStatus),)
    _kernel32.GlobalMemoryStatusEx.restype = wintypes.BOOL
    _psapi.GetProcessMemoryInfo.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_ProcessMemory),
        wintypes.DWORD,
    )
    _psapi.GetProcessMemoryInfo.restype = wintypes.BOOL


def _physical_memory(windows_field: str, linux_field: str) -> int | None:
    """Un dato de la memoria física del equipo; ``None`` si este sistema no permite medirlo."""
    if sys.platform == "win32":
        status = _MemoryStatus()
        status.dwLength = ctypes.sizeof(_MemoryStatus)
        if not _kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return int(getattr(status, windows_field))
    try:
        text = Path("/proc/meminfo").read_text(encoding="ascii")
    except OSError:
        return None
    return kib_field(text, linux_field)


def available_memory_bytes() -> int | None:
    """Memoria física disponible en el equipo; ``None`` si este sistema no permite medirla."""
    return _physical_memory("ullAvailPhys", "MemAvailable")


def total_memory_bytes() -> int | None:
    """Memoria física total del equipo; ``None`` si este sistema no permite medirla."""
    return _physical_memory("ullTotalPhys", "MemTotal")


class MemoryProbe:
    """Mide la memoria máxima de un proceso hijo, también después de que termine.

    En Windows guarda un acceso al proceso desde que nace: el sistema conserva su máximo aunque
    ya haya terminado. En Linux lee ``/proc`` mientras vive y recuerda el último máximo.
    """

    def __init__(self, pid: int) -> None:
        self._pid = pid
        self._handle: int | None = None
        self._last: int | None = None
        if sys.platform == "win32":
            handle = _kernel32.OpenProcess(_WINDOWS_ACCESS, False, pid)
            self._handle = int(handle) if handle else None

    def peak_bytes(self) -> int | None:
        """Máximo de memoria residente del proceso hasta ahora; ``None`` si no se puede medir."""
        if sys.platform == "win32":
            self._windows_peak()
        else:
            try:
                text = Path(f"/proc/{self._pid}/status").read_text(encoding="ascii")
            except OSError:
                return self._last
            peak = kib_field(text, "VmHWM")
            if peak is not None:
                self._last = peak
        return self._last

    def _windows_peak(self) -> None:
        if self._handle is None:
            return
        info = _ProcessMemory()
        info.cb = ctypes.sizeof(_ProcessMemory)
        if _psapi.GetProcessMemoryInfo(self._handle, ctypes.byref(info), info.cb):
            self._last = int(info.PeakWorkingSetSize)

    def close(self) -> None:
        """Libera el acceso al proceso. Es seguro llamarlo más de una vez."""
        if sys.platform == "win32" and self._handle is not None:
            _kernel32.CloseHandle(self._handle)
        self._handle = None
