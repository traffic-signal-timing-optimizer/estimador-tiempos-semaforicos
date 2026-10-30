"""Modelo tipado del caso (contrato ``case`` v1.0, DEV02).

Un caso describe lo que comparten todos los procesos del experimento: movimientos, secuencia de
slots y restricciones. Este módulo contiene solo reglas puras: no lee archivos ni lanza procesos
(ADR01). La lectura del archivo está en ``semaforo.caso.case_validation``.

Reglas de estructura (acta ``2026-10-29-dev02-f0-decisiones.md``):

- CASE-S01: contrato v1.0 completo, sin campos desconocidos, con tipos exactos (sin conversión) y
  sin NaN ni infinito.
- CASE-S02: los identificadores no están vacíos ni llevan espacios al inicio o al final,
  caracteres de control o caracteres invisibles.
- CASE-S03: ``case_version`` tiene el formato ``MAYOR.MENOR.PARCHE``.
- CASE-S04: tamaño máximo del archivo; lo comprueba el lector, que es quien conoce los bytes.

Los problemas se informan todos juntos, cada uno con su regla, su campo y su motivo.
"""

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, Field, ValidationError
from pydantic_core import PydanticCustomError

from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.errors import DomainError, ErrorCode

__all__ = [
    "MAX_ISSUES",
    "Artifact",
    "Case",
    "CaseInvalidError",
    "CaseIssue",
    "GreenGroup",
    "Movement",
    "Range",
    "Slot",
    "State",
    "canonical_sha256",
    "cap_issues",
    "omitted_issue",
    "parse_case",
]

STRUCTURE_RULE = "CASE-S01"
IDENTIFIER_RULE = "CASE-S02"
VERSION_RULE = "CASE-S03"
SIZE_RULE = "CASE-S04"
MAX_ISSUES = 100
VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
SHA256_PATTERN = r"^[a-f0-9]{64}$"
STATE_PATTERN = r"^[rRyYgGsuoO]+$"
# Categorías Unicode que no se admiten en un identificador: control (Cc) y formato (Cf), que
# incluye los caracteres invisibles como el espacio de ancho cero.
HIDDEN_CATEGORIES = frozenset({"Cc", "Cf"})
_CUSTOM_RULES = {"case_s02": IDENTIFIER_RULE, "case_s03": VERSION_RULE}


def _identifier(value: str) -> str:
    """Rechaza un texto vacío, con espacios en los extremos, de control o invisible."""
    if (
        not value
        or value != value.strip()
        or any(unicodedata.category(character) in HIDDEN_CATEGORIES for character in value)
    ):
        raise PydanticCustomError(
            "case_s02",
            "el identificador no puede estar vacío, tener espacios al inicio o al final, "
            "ni caracteres de control o invisibles",
        )
    return value


def _version(value: str) -> str:
    """Exige el formato ``MAYOR.MENOR.PARCHE`` con números sin ceros a la izquierda."""
    if VERSION_PATTERN.fullmatch(value) is None:
        raise PydanticCustomError(
            "case_s03",
            "la versión del caso debe tener el formato MAYOR.MENOR.PARCHE, por ejemplo 1.0.0",
        )
    return value


Identifier = Annotated[str, AfterValidator(_identifier)]
Version = Annotated[str, AfterValidator(_version)]


class Artifact(FrozenModel):
    """Archivo con huella: la red del caso."""

    artifact_id: Identifier
    path: str
    sha256: str = Field(pattern=SHA256_PATTERN)


class Range(FrozenModel):
    """Intervalo cerrado de números no negativos. Que el mínimo no supere al máximo lo comprueba
    la regla CASE-C02 (F2)."""

    min: float = Field(ge=0)
    max: float = Field(ge=0)


class State(FrozenModel):
    """Estado de las señales de un semáforo (TLS) durante un slot, una letra por enlace."""

    tls_id: Identifier
    state: str = Field(pattern=STATE_PATTERN)


class Slot(FrozenModel):
    """Intervalo de la secuencia en el que ningún estado cambia."""

    id: Identifier
    kind: Literal["variable", "fixed"]
    min_s: float = Field(gt=0)
    max_s: float = Field(gt=0)
    states: list[State] = Field(min_length=1)


class Movement(FrozenModel):
    """Movimiento vehicular y los enlaces del semáforo que lo controlan."""

    id: Identifier
    approach_id: Identifier
    incoming_lanes: list[Identifier] = Field(min_length=1)
    outgoing_edges: list[Identifier] = Field(min_length=1)
    tls_id: Identifier
    link_indices: list[int] = Field(min_length=1)
    flow_domain_vph: Range


class GreenGroup(FrozenModel):
    """Grupo de verde: los slots cuya suma da el verde mostrado de un movimiento o un paso."""

    id: Identifier
    slot_ids: list[Identifier] = Field(min_length=1)
    min_s: float = Field(ge=0)
    max_s: float = Field(gt=0)
    purpose: Literal["vehicle", "pedestrian"]


class Case(FrozenModel):
    """Caso versionado (contrato ``case`` v1.0)."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    case_id: Identifier
    case_version: Version
    origin: Literal["synthetic", "field"]
    description: str
    representation_status: Literal["synthetic_fixture", "unverified", "calibrated", "validated"]
    network: Artifact | None
    tick_s: float = Field(gt=0)
    cycle_s: Range
    vehicle_classes: list[Identifier] = Field(min_length=1)
    movements: list[Movement] = Field(min_length=1)
    slots: list[Slot] = Field(min_length=1)
    green_groups: list[GreenGroup] = Field(min_length=1)
    boundary_policy_id: Identifier
    restrictions_evidence: list[str]


@dataclass(frozen=True)
class CaseIssue:
    """Un problema del caso: la regla incumplida, el campo y el motivo.

    ``field`` es None si el problema es del caso entero.
    """

    rule_id: str
    field: str | None
    message: str


class CaseInvalidError(DomainError):
    """El caso no cumple el contrato. Lleva todos los problemas, el primero en el mensaje.

    El código es INPUT_SCHEMA, que la CLI traduce al código de salida 2.
    """

    def __init__(self, issues: Sequence[CaseIssue]) -> None:
        if not issues:
            raise ValueError("un caso inválido tiene al menos un problema")
        first = issues[0]
        extra = f" (y {len(issues) - 1} más)" if len(issues) > 1 else ""
        where = "" if first.field is None else f" en {first.field}"
        super().__init__(
            ErrorCode.INPUT_SCHEMA,
            f"el caso no es válido: {first.rule_id}{where}: {first.message}{extra}",
            first.field,
        )
        self.issues = tuple(issues)


def _field_path(location: Sequence[int | str]) -> str | None:
    """Ruta legible de un campo, por ejemplo ``slots[2].max_s``; None para el caso entero."""
    path = ""
    for part in location:
        path += f"[{part}]" if isinstance(part, int) else (f".{part}" if path else part)
    return path or None


_MESSAGES = {
    "missing": "falta el campo obligatorio",
    "extra_forbidden": "campo desconocido: el contrato v1.0 no lo admite",
    "string_type": "debe ser un texto",
    "int_type": "debe ser un número entero",
    "float_type": "debe ser un número",
    "list_type": "debe ser una lista",
    "model_type": "debe ser un objeto",
    "dict_type": "debe ser un objeto",
    "finite_number": "debe ser un número finito (sin NaN ni infinito)",
    "literal_error": "valor no admitido; valores posibles: {expected}",
    "string_pattern_mismatch": "no cumple el formato {pattern}",
    "greater_than": "debe ser mayor que {gt}",
    "greater_than_equal": "debe ser mayor o igual que {ge}",
    "too_short": "debe tener al menos {min_length} elemento(s)",
}


def _display(value: object) -> str:
    """Número sin decimales sobrantes (0 y no 0.0); el resto, como texto."""
    return f"{value:g}" if isinstance(value, int | float) else str(value).replace(" or ", " o ")


def _message(error_type: str, context: Mapping[str, Any], fallback: str) -> str:
    """Motivo en español de un error de validación; los propios del caso ya vienen en español."""
    template = _MESSAGES.get(error_type)
    if template is None:
        return fallback if error_type in _CUSTOM_RULES else f"valor no válido: {fallback}"
    try:
        return template.format_map({key: _display(value) for key, value in context.items()})
    except KeyError:
        return fallback


def omitted_issue(count: int, rule_id: str) -> CaseIssue:
    """Último problema de una lista recortada: dice cuántos no se muestran."""
    noun = "problema" if count == 1 else "problemas"
    return CaseIssue(rule_id, None, f"y {count} {noun} más sin mostrar")


def cap_issues(issues: Sequence[CaseIssue]) -> list[CaseIssue]:
    """Los primeros ``MAX_ISSUES`` problemas y, si hay más, uno final que cuenta los omitidos.

    El problema final lleva la regla del primero omitido.
    """
    if len(issues) <= MAX_ISSUES:
        return list(issues)
    return [
        *issues[:MAX_ISSUES],
        omitted_issue(len(issues) - MAX_ISSUES, issues[MAX_ISSUES].rule_id),
    ]


def issues_of(error: ValidationError) -> list[CaseIssue]:
    """Problemas de un ``ValidationError``, con regla, campo y motivo en español.

    Se informan como máximo ``MAX_ISSUES``; si hay más, el último problema indica cuántos faltan.
    """
    found = error.errors(include_url=False, include_context=True)
    issues = [
        CaseIssue(
            _CUSTOM_RULES.get(item["type"], STRUCTURE_RULE),
            _field_path(item["loc"]),
            _message(item["type"], item.get("ctx") or {}, item["msg"]),
        )
        for item in found[: MAX_ISSUES + 1]
    ]
    if len(found) > MAX_ISSUES:
        return [
            *issues[:MAX_ISSUES],
            omitted_issue(len(found) - MAX_ISSUES, issues[MAX_ISSUES].rule_id),
        ]
    return issues


def parse_case(data: object) -> Case:
    """Valida ``data`` (el contenido ya leído del JSON) y devuelve el caso.

    Raises:
        CaseInvalidError: si no cumple el contrato, con todos los problemas encontrados.
    """
    try:
        return Case.model_validate(data)
    except ValidationError as error:
        raise CaseInvalidError(issues_of(error)) from None


def canonical_sha256(case: Case) -> str:
    """Huella SHA-256 del contenido del caso en JSON canónico (claves ordenadas, sin espacios).

    Dos archivos con el mismo contenido dan la misma huella aunque cambien los espacios, los saltos
    de línea o el orden de las claves; cualquier cambio de valor la cambia.
    """
    canonical = json.dumps(
        case.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
