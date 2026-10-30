"""Reporte del caso (DEV02, F3): estado, huella, límites efectivos y resultado de cada regla.

El reporte se produce también con un caso inválido: ``limits`` y ``case_sha256`` quedan en None
solo si no se llegó a leer la estructura del caso. Cada regla aparece siempre, en el mismo orden,
con estado ``passed``, ``warning``, ``failed`` o ``not_applicable``.
"""

from collections.abc import Iterable
from typing import Literal

from pydantic import Field

from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.case import CaseIssue
from semaforo.dominio.errors import ErrorCode

__all__ = [
    "REPORT_EXIT_CODES",
    "CaseReport",
    "GroupLimits",
    "Interval",
    "Limits",
    "NetworkStatus",
    "ReportIssue",
    "ReportStatus",
    "RuleOutcome",
    "RuleStatus",
    "to_report_issues",
]

ReportStatus = Literal["valid", "valid_with_warnings", "invalid"]
NetworkStatus = Literal["not_declared", "not_checked", "verified", "failed"]
RuleStatus = Literal["passed", "warning", "failed", "not_applicable"]
REPORT_SCHEMA_VERSION = "1.0.0"
# Códigos de salida del reporte (diseño técnico, «Errores y códigos de salida»). Son los mismos de
# ``semaforo.app.exit_codes``. El módulo caso no puede importar app (ADR01), así que una prueba
# comprueba que coincidan.
REPORT_EXIT_CODES: dict[ErrorCode, int] = {
    ErrorCode.INPUT_SCHEMA: 2,
    ErrorCode.DEPENDENCY_MISSING: 3,
    ErrorCode.HASH_MISMATCH: 5,
    ErrorCode.PATH_NOT_ALLOWED: 5,
}


class ReportIssue(FrozenModel):
    """Un problema: el campo afectado (None si es del caso entero) y el motivo en español."""

    field: str | None
    message: str


class RuleOutcome(FrozenModel):
    """Resultado de una regla. Los problemas van en la misma lista que el estado."""

    rule_id: str
    title: str
    status: RuleStatus
    issues: list[ReportIssue]


class Interval(FrozenModel):
    """Intervalo cerrado de duraciones, en segundos."""

    min: float
    max: float


class GroupLimits(FrozenModel):
    """Verde declarado de un grupo y el que se puede alcanzar con sus slots (None si no hay)."""

    id: str
    declared_s: Interval
    reachable_s: Interval | None


class Limits(FrozenModel):
    """Límites efectivos del caso: los que el plan debe respetar."""

    tick_s: float
    cycle_declared_s: Interval
    cycle_feasible_s: Interval | None
    fixed_time_s: float = Field(ge=0)
    variable_slots: int = Field(ge=0)
    green_groups: list[GroupLimits]


class CaseReport(FrozenModel):
    """Reporte de validación de un caso y, si lo declara, de su red."""

    schema_version: Literal["1.0.0"] = REPORT_SCHEMA_VERSION
    case_id: str | None
    case_version: str | None
    origin: str | None
    representation_status: str | None
    case_sha256: str | None
    status: ReportStatus
    exit_code: int = Field(ge=0)
    network: NetworkStatus
    limits: Limits | None
    error: str | None
    rules: list[RuleOutcome]


def to_report_issues(issues: Iterable[CaseIssue]) -> list[ReportIssue]:
    """Problemas del dominio, en la forma del reporte."""
    return [ReportIssue(field=issue.field, message=issue.message) for issue in issues]
