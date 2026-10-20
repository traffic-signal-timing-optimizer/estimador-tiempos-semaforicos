"""Errores de dominio del módulo caso."""

from enum import StrEnum


class ErrorCode(StrEnum):
    """Códigos estables de error, para que la CLI los traduzca a un código de salida.

    INPUT_SCHEMA y HASH_MISMATCH figuran en la lista de códigos de la documentación.
    PATH_NOT_ALLOWED lo añade DEV00: cubre rutas fuera de la carpeta permitida y enlaces.
    """

    INPUT_SCHEMA = "INPUT_SCHEMA"
    HASH_MISMATCH = "HASH_MISMATCH"
    PATH_NOT_ALLOWED = "PATH_NOT_ALLOWED"


class CasoError(Exception):
    """Error de dominio con estado y motivo: lleva un código estable y el campo afectado."""

    def __init__(self, code: ErrorCode, message: str, field: str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.field = field
