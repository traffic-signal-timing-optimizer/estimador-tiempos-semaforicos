"""Pruebas de la traducción de códigos de error a códigos de salida (diseño técnico)."""

import pytest

from semaforo.app.exit_codes import exit_code_for
from semaforo.dominio.errors import ErrorCode

# Diseño técnico, «Errores y códigos de salida»: 2 sintaxis o archivo/esquema inválido;
# 3 artefacto incompatible o dependencia faltante; 4 fallo de proceso o timeout;
# 5 fallo de integridad o autorización de ruta.
EXPECTED = {
    ErrorCode.INPUT_SCHEMA: 2,
    ErrorCode.DEPENDENCY_MISSING: 3,
    ErrorCode.SIM_FAILED: 4,
    ErrorCode.SIM_TIMEOUT: 4,
    ErrorCode.OUTPUT_INVALID: 4,
    ErrorCode.HASH_MISMATCH: 5,
    ErrorCode.PATH_NOT_ALLOWED: 5,
    ErrorCode.RUN_EXISTS: 5,
}


def test_every_error_code_has_an_exit_code() -> None:
    assert set(EXPECTED) == set(ErrorCode)


@pytest.mark.parametrize(("code", "expected"), EXPECTED.items(), ids=[c.value for c in EXPECTED])
def test_exit_code_for(code: ErrorCode, expected: int) -> None:
    assert exit_code_for(code) == expected
    assert exit_code_for(code.value) == expected


def test_an_unknown_code_is_an_internal_error() -> None:
    assert exit_code_for("DESCONOCIDO") == 1
