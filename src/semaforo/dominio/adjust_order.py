"""Orden de ajuste del ciclo de un caso (DEV13 F3; decisiones D6 y D18 de F0).

Cuando un plan propuesto se pasa del ciclo máximo, el corrector le quita tiempo a los slots
variables **uno tras otro** en este orden, cada uno hasta su mínimo. Si se queda corto del ciclo
mínimo, se lo da en el orden **inverso** (el último en perder es el primero en ganar), cada uno
hasta su máximo. El orden es un dato de cada caso, no del código: así la herramienta sirve para
cualquier cruce, cada uno con el suyo. Si un caso no tiene archivo, se usa el orden de la
secuencia para quitar y para dar, como dice el diseño técnico al pie de la letra.

El archivo (JSON, versión 1.0.0) dice a qué caso y versión pertenece, la lista de slots variables
en el orden en que pierden tiempo, y de dónde sale ese orden. No es uno de los contratos
publicados del proyecto. Es puro: la lectura del archivo está en ``semaforo.caso``.

Reglas (los problemas se informan todos juntos, con regla, campo y motivo):

- ORDER-S01 a S03: estructura, como las del caso: campos exactos, identificadores válidos y
  versión ``MAYOR.MENOR.PARCHE``.
- ORDER-C01: el orden es del caso y de la versión que se están usando.
- ORDER-C02: cada slot variable del caso aparece exactamente una vez.
- ORDER-C03: no aparece ningún slot fijo ni ninguno que el caso no tenga.
"""

from collections.abc import Sequence
from typing import Literal

from pydantic import Field, ValidationError

from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.case import (
    Case,
    CaseIssue,
    Identifier,
    Version,
    cap_issues,
    issues_of,
)
from semaforo.dominio.errors import DomainError, ErrorCode

__all__ = [
    "AdjustOrder",
    "AdjustOrderInvalidError",
    "order_issues",
    "parse_adjust_order",
]

CASE_RULE = "ORDER-C01"
COVERAGE_RULE = "ORDER-C02"
KNOWN_RULE = "ORDER-C03"


class AdjustOrder(FrozenModel):
    """Orden en que los slots variables de un caso pierden tiempo cuando el ciclo se pasa."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    case_id: Identifier
    case_version: Version
    cut_order: list[Identifier] = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)


class AdjustOrderInvalidError(DomainError):
    """El orden de ajuste no sirve para el caso. Lleva todos los problemas.

    El código es INPUT_SCHEMA, que la CLI traduce al código de salida 2.
    """

    def __init__(self, issues: Sequence[CaseIssue]) -> None:
        if not issues:
            raise ValueError("un orden inválido tiene al menos un problema")
        first = issues[0]
        extra = f" (y {len(issues) - 1} más)" if len(issues) > 1 else ""
        where = "" if first.field is None else f" en {first.field}"
        super().__init__(
            ErrorCode.INPUT_SCHEMA,
            f"el orden de ajuste no es válido: {first.rule_id}{where}: {first.message}{extra}",
            first.field,
        )
        self.issues = tuple(issues)


def parse_adjust_order(data: object) -> AdjustOrder:
    """Valida ``data`` (el contenido ya leído del JSON) y devuelve el orden.

    Raises:
        AdjustOrderInvalidError: si no cumple la estructura (ORDER-S01 a S03), con todos los
            problemas encontrados.
    """
    try:
        return AdjustOrder.model_validate(data)
    except ValidationError as error:
        raise AdjustOrderInvalidError(
            [
                CaseIssue(issue.rule_id.replace("CASE-", "ORDER-", 1), issue.field, issue.message)
                for issue in issues_of(error)
            ]
        ) from None


def order_issues(case: Case, order: AdjustOrder) -> list[CaseIssue]:
    """Problemas del orden frente al caso (ORDER-C01 a C03), o lista vacía si sirve."""
    issues: list[CaseIssue] = []
    if order.case_id != case.case_id:
        issues.append(
            CaseIssue(
                CASE_RULE,
                "case_id",
                f"el orden es del caso {order.case_id!r} y el caso es {case.case_id!r}",
            )
        )
    if order.case_version != case.case_version:
        issues.append(
            CaseIssue(
                CASE_RULE,
                "case_version",
                f"el orden es de la versión {order.case_version!r} y el caso es "
                f"{case.case_version!r}",
            )
        )
    kinds = {slot.id: slot.kind for slot in case.slots}
    seen: set[str] = set()
    for index, slot_id in enumerate(order.cut_order):
        field = f"cut_order[{index}]"
        if slot_id in seen:
            issues.append(CaseIssue(COVERAGE_RULE, field, f"el slot {slot_id!r} está repetido"))
        elif slot_id not in kinds:
            issues.append(CaseIssue(KNOWN_RULE, field, f"el slot {slot_id!r} no es del caso"))
        elif kinds[slot_id] == "fixed":
            issues.append(
                CaseIssue(KNOWN_RULE, field, f"el slot {slot_id!r} es fijo: su duración no cambia")
            )
        seen.add(slot_id)
    issues.extend(
        CaseIssue(COVERAGE_RULE, "cut_order", f"falta el slot variable {slot.id!r}")
        for slot in case.slots
        if slot.kind == "variable" and slot.id not in seen
    )
    return cap_issues(issues)
