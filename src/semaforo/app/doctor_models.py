"""Modelos del diagnóstico del entorno (``python -m semaforo doctor``, DEV01)."""

from typing import Literal, Self

from pydantic import model_validator

from semaforo.dominio.base_model import FrozenModel

CheckStatus = Literal["ok", "warning", "error"]
DoctorStatus = Literal["ok", "warnings", "failed"]


class Check(FrozenModel):
    """Resultado de una comprobación del entorno.

    ``value`` es lo medido (una versión, una ruta o una cantidad de bytes), o None si no se pudo
    medir. ``code`` es el código de error estable y solo existe cuando ``status`` es ``error``.
    """

    name: str
    status: CheckStatus
    value: str | int | None
    message: str
    code: str | None = None

    @model_validator(mode="after")
    def _code_only_for_errors(self) -> Self:
        if (self.status == "error") != (self.code is not None):
            raise ValueError("una comprobación lleva código si y solo si es un error")
        return self


class DoctorReport(FrozenModel):
    """Diagnóstico completo, en el orden fijo de las comprobaciones.

    ``status`` es ``failed`` si alguna comprobación es un error, ``warnings`` si solo hay avisos y
    ``ok`` si todo está bien. ``exit_code`` es el código de salida de la CLI.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: DoctorStatus
    exit_code: int
    checks: list[Check]
