"""Error del módulo de referencias (DEV14)."""

from semaforo.dominio.errors import DomainError

__all__ = ["ReferenciasError"]


class ReferenciasError(DomainError):
    """No se puede buscar: parámetros fuera de rango, un plan auxiliar que no es del caso o una
    búsqueda que no es la que se dice. Lleva código y motivo; nunca se devuelve una lista a medias.
    """
