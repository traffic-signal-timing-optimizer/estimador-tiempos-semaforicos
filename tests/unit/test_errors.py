"""Pruebas de los errores de dominio compartidos entre módulos."""

from semaforo.caso.errors import CasoError
from semaforo.caso.errors import ErrorCode as CasoErrorCode
from semaforo.dominio.errors import DomainError, ErrorCode


def test_caso_errors_are_domain_errors_with_the_shared_codes() -> None:
    error = CasoError(ErrorCode.HASH_MISMATCH, "la copia no coincide", "net.xml")
    assert isinstance(error, DomainError)
    assert CasoErrorCode is ErrorCode
    assert (error.code, error.message, error.field) == (
        ErrorCode.HASH_MISMATCH,
        "la copia no coincide",
        "net.xml",
    )
    assert str(error) == "HASH_MISMATCH: la copia no coincide"
