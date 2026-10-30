"""Códigos de salida de la CLI, comunes a todos los comandos (diseño técnico, «Errores y códigos de
salida»).

0 operación completada; 2 sintaxis o archivo/esquema inválido; 3 artefacto incompatible o
dependencia faltante; 4 fallo de proceso o tiempo agotado; 5 fallo de integridad o ruta no
permitida. El 1 es un error interno.
"""

from semaforo.dominio.errors import ErrorCode

__all__ = ["EXIT_CODES", "INTERNAL_ERROR_EXIT", "exit_code_for"]

INTERNAL_ERROR_EXIT = 1
EXIT_CODES: dict[ErrorCode, int] = {
    ErrorCode.INPUT_SCHEMA: 2,
    ErrorCode.DEPENDENCY_MISSING: 3,
    ErrorCode.SIM_FAILED: 4,
    ErrorCode.SIM_TIMEOUT: 4,
    ErrorCode.OUTPUT_INVALID: 4,
    ErrorCode.HASH_MISMATCH: 5,
    ErrorCode.PATH_NOT_ALLOWED: 5,
    ErrorCode.RUN_EXISTS: 5,
}


def exit_code_for(code: ErrorCode | str) -> int:
    """Código de salida de la CLI para un código de error; 1 si no se reconoce."""
    try:
        return EXIT_CODES[ErrorCode(code)]
    except (ValueError, KeyError):
        return INTERNAL_ERROR_EXIT
