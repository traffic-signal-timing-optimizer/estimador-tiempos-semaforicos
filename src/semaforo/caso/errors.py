"""Errores de dominio del módulo caso. Los códigos son los compartidos de ``dominio.errors``."""

from semaforo.dominio.errors import DomainError, ErrorCode

__all__ = ["CasoError", "ErrorCode"]


class CasoError(DomainError):
    """Error de la recepción de un caso: copia, inventario o auditoría."""
