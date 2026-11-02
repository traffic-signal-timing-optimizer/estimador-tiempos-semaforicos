"""Error del módulo de evaluación (DEV19)."""

from semaforo.dominio.errors import DomainError

__all__ = ["EvaluacionError"]


class EvaluacionError(DomainError):
    """No se pueden calcular las métricas: salidas incoherentes, protocolo no admitido o una
    corrida que no es la que se dice. Lleva código y motivo; nunca se devuelven cifras a medias.
    """
