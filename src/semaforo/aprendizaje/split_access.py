"""Bloqueo de la fuga de la prueba hacia el ajuste (DEV12 F2, HU07; decisión D9 de F0, ADR07).

El ajuste, la selección y el refit trabajan sobre la **vista de desarrollo**: solo los
identificadores y los grupos de entrenamiento y de validación. No existe ningún atributo con los de
la prueba, así que quien recibe la vista no puede pedirlos. Es aislamiento lógico y verificable, no
una convención.

Cada acceso declara su finalidad, y solo se permiten estas combinaciones:

=================  ===========================================================================
Finalidad          Particiones que se pueden pedir
=================  ===========================================================================
``fit``            ``train`` (ajustar el modelo y sus transformaciones)
``select``         ``validation`` (comparar candidatos y elegir)
``refit``          ``train`` y ``validation`` (repetir el ajuste con la configuración ya fija)
``final_evaluation``  ``test`` (una evaluación final, con el protocolo congelado)
=================  ===========================================================================

Pedir la prueba para ajustar, seleccionar o hacer el refit, o pedir entrenamiento para la
evaluación final, es un ``LeakageError`` que dice qué se pidió. Un identificador que la partición no
conoce también se rechaza: sin saber de qué parte viene, no se puede usar.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.dominio.split import Partition, Split
from semaforo.trazabilidad.hashing import sha256_bytes

__all__ = [
    "ALLOWED",
    "MAX_SHOWN",
    "DevelopmentView",
    "LeakageError",
    "Purpose",
    "check_ids",
    "development_view",
    "ids_for",
    "rows_digest",
    "rows_for",
]

Purpose = Literal["fit", "select", "refit", "final_evaluation"]
ALLOWED: dict[Purpose, tuple[Partition, ...]] = {
    "fit": ("train",),
    "select": ("validation",),
    "refit": ("train", "validation"),
    "final_evaluation": ("test",),
}
MAX_SHOWN = 10


class LeakageError(DomainError):
    """Se pidió algo que dejaría pasar la prueba al ajuste (o el entrenamiento a la prueba).

    El código es INPUT_SCHEMA: es una petición que no se puede atender.
    """

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(ErrorCode.INPUT_SCHEMA, message, field)


@dataclass(frozen=True)
class DevelopmentView:
    """Lo que ve quien ajusta o selecciona: entrenamiento y validación, y nada de la prueba."""

    split_id: str
    train_ids: tuple[str, ...]
    validation_ids: tuple[str, ...]
    train_groups: tuple[str, ...]
    validation_groups: tuple[str, ...]

    @property
    def development_ids(self) -> tuple[str, ...]:
        """Entrenamiento y validación juntos (para el refit con la configuración ya fija)."""
        return (*self.train_ids, *self.validation_ids)


def _partition_of(split: Split) -> dict[str, Partition]:
    return {assignment.scenario_id: assignment.partition for assignment in split.assignments}


def development_view(split: Split) -> DevelopmentView:
    """La vista de desarrollo de ``split``: escenarios y grupos de entrenamiento y validación."""

    def pick(partition: Partition) -> tuple[tuple[str, ...], tuple[str, ...]]:
        found = [a for a in split.assignments if a.partition == partition]
        ids = tuple(a.scenario_id for a in found)
        groups = tuple(dict.fromkeys(a.group_id for a in found))
        return ids, groups

    train_ids, train_groups = pick("train")
    validation_ids, validation_groups = pick("validation")
    return DevelopmentView(
        split.split_id, train_ids, validation_ids, train_groups, validation_groups
    )


def _check_purpose(purpose: str) -> tuple[Partition, ...]:
    for name, allowed in ALLOWED.items():
        if name == purpose:
            return allowed
    raise LeakageError(
        f"finalidad «{purpose}» desconocida; las posibles son: {', '.join(ALLOWED)}", "purpose"
    )


def _names(partitions: Sequence[str]) -> str:
    return ", ".join(partitions)


def ids_for(split: Split, partition: Partition, purpose: Purpose) -> tuple[str, ...]:
    """Los identificadores de ``partition`` si ``purpose`` los permite.

    Raises:
        LeakageError: si la finalidad no admite esa partición (por ejemplo, la prueba para
            ajustar) o la finalidad no existe.
    """
    allowed = _check_purpose(purpose)
    if partition not in allowed:
        raise LeakageError(
            f"para «{purpose}» solo se pueden pedir: {_names(allowed)}; se pidió «{partition}»",
            "partition",
        )
    return tuple(a.scenario_id for a in split.assignments if a.partition == partition)


def check_ids(split: Split, scenario_ids: Sequence[str], purpose: Purpose) -> None:
    """Todos los ``scenario_ids`` son de particiones que ``purpose`` permite.

    Raises:
        LeakageError: con los identificadores que no cumplen (hasta ``MAX_SHOWN``), diciendo de
            qué partición vienen o que la partición no los conoce.
    """
    allowed = _check_purpose(purpose)
    partition_of = _partition_of(split)
    offending = [
        (scenario_id, partition_of.get(scenario_id))
        for scenario_id in scenario_ids
        if partition_of.get(scenario_id) not in allowed
    ]
    if not offending:
        return
    shown = ", ".join(
        f"«{scenario_id}» ({'desconocido' if partition is None else partition})"
        for scenario_id, partition in offending[:MAX_SHOWN]
    )
    more = "" if len(offending) <= MAX_SHOWN else f" y {len(offending) - MAX_SHOWN} más"
    raise LeakageError(
        f"para «{purpose}» solo se admiten escenarios de: {_names(allowed)}; "
        f"no sirven {shown}{more}",
        "scenario_ids",
    )


def rows_for[T](split: Split, rows: Mapping[str, T], purpose: Purpose) -> dict[str, T]:
    """Las filas de ``rows`` que ``purpose`` permite, en el orden de la partición.

    Las filas de otras particiones no se devuelven (ni se leen sus valores): quien ajusta recibe
    solo entrenamiento aunque ``rows`` tenga también las etiquetas de la prueba.

    Raises:
        LeakageError: si alguna clave de ``rows`` no es un escenario de la partición, o la
            finalidad no existe.
    """
    allowed = _check_purpose(purpose)
    partition_of = _partition_of(split)
    unknown = [scenario_id for scenario_id in rows if scenario_id not in partition_of]
    if unknown:
        shown = ", ".join(f"«{scenario_id}»" for scenario_id in unknown[:MAX_SHOWN])
        more = "" if len(unknown) <= MAX_SHOWN else f" y {len(unknown) - MAX_SHOWN} más"
        raise LeakageError(f"la partición no conoce estos escenarios: {shown}{more}", "rows")
    return {
        assignment.scenario_id: rows[assignment.scenario_id]
        for assignment in split.assignments
        if assignment.partition in allowed and assignment.scenario_id in rows
    }


def rows_digest(rows: Mapping[str, float]) -> str:
    """Huella SHA-256 de las filas, en orden de escenario: una línea ``<escenario>\t<valor>``.

    Sirve para dejar anotado qué consumió un ajuste: si la prueba no se cuela, la huella de las
    filas de ajuste es la misma aunque se altere cualquier valor de la prueba (QA15).
    """
    text = "".join(f"{scenario_id}\t{value!r}\n" for scenario_id, value in sorted(rows.items()))
    return sha256_bytes(text.encode("utf-8"))
