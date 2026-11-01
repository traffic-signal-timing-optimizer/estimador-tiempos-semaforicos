"""Que SUMO muera con el programa que lo lanzó (DEV07 F3, D8).

Si el programa se termina a la fuerza (cierre desde el administrador de tareas, apagón de la
sesión), un SUMO lanzado por él seguiría vivo y escribiendo en la carpeta de la corrida, sin nadie
que lo vigile ni lo limite. En Windows se evita metiéndolo en un «objeto de trabajo» marcado para
matar a todos sus procesos cuando se cierra el último acceso a él: el sistema lo cierra al morir el
programa. Sin dependencias nuevas (``ctypes``).

En otros sistemas no hace nada: un SUMO huérfano no se corta (límite conocido, ver el acta de F3).
"""

import ctypes
import sys

__all__ = ["KillOnClose"]

# PROCESS_SET_QUOTA | PROCESS_TERMINATE
_ACCESS = 0x0100 | 0x0001
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_KILL_ON_JOB_CLOSE = 0x00002000

if sys.platform == "win32":
    from ctypes import wintypes

    class _BasicLimits(ctypes.Structure):
        _fields_ = (
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        )

    class _IoCounters(ctypes.Structure):
        _fields_ = tuple((name, ctypes.c_ulonglong) for name in ("r", "w", "o", "rb", "wb", "ob"))

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = (
            ("BasicLimitInformation", _BasicLimits),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        )

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.CloseHandle.restype = wintypes.BOOL


class KillOnClose:
    """Agrupa un proceso para que el sistema lo mate si este programa muere.

    ``attach`` devuelve ``None`` si no se pudo (otro sistema, o el proceso ya pertenece a un
    trabajo que no lo permite): la corrida sigue, solo sin esta garantía. ``close`` cierra el
    grupo y, con eso, mata lo que siga vivo dentro.
    """

    def __init__(self, handle: int) -> None:
        self._handle: int | None = handle

    @classmethod
    def attach(cls, pid: int) -> "KillOnClose | None":
        """Mete al proceso ``pid`` en un grupo que se mata al cerrarse."""
        if sys.platform != "win32":
            return None
        job = _kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
        process = _kernel32.OpenProcess(_ACCESS, False, pid)
        ready = bool(process) and bool(
            _kernel32.SetInformationJobObject(
                job,
                _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            )
        )
        ready = ready and bool(_kernel32.AssignProcessToJobObject(job, process))
        if process:
            _kernel32.CloseHandle(process)
        if not ready:
            _kernel32.CloseHandle(job)
            return None
        return cls(int(job))

    def close(self) -> None:
        """Cierra el grupo: mata lo que siga vivo en él. Es seguro llamarlo más de una vez."""
        handle, self._handle = self._handle, None
        if sys.platform == "win32" and handle is not None:
            _kernel32.CloseHandle(handle)
