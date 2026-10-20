"""Errores de dominio con códigos estables, compartidos por todos los módulos."""

from enum import StrEnum


class ErrorCode(StrEnum):
    """Códigos estables de error, para que la CLI los traduzca a un código de salida.

    INPUT_SCHEMA, OUTPUT_INVALID, HASH_MISMATCH, SIM_FAILED y SIM_TIMEOUT figuran en la lista de
    códigos de dominio del diseño técnico. PATH_NOT_ALLOWED, RUN_EXISTS y DEPENDENCY_MISSING los
    añade DEV00: rutas fuera de la carpeta permitida o enlaces, una ejecución que ya existe o que
    otro proceso está escribiendo, y una dependencia externa (SUMO) que no se encuentra.
    """

    INPUT_SCHEMA = "INPUT_SCHEMA"
    OUTPUT_INVALID = "OUTPUT_INVALID"
    HASH_MISMATCH = "HASH_MISMATCH"
    SIM_FAILED = "SIM_FAILED"
    SIM_TIMEOUT = "SIM_TIMEOUT"
    PATH_NOT_ALLOWED = "PATH_NOT_ALLOWED"
    RUN_EXISTS = "RUN_EXISTS"
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"


class DomainError(Exception):
    """Error de dominio con estado y motivo: lleva un código estable y el campo afectado."""

    def __init__(self, code: ErrorCode, message: str, field: str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.field = field
