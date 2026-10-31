"""Control de calidad de aforos: comparación con el conteo de control (DEV05, HU03).

Compara un conteo principal con un conteo de control del mismo caso (decisiones D1 a D3 de
``2026-10-30-dev05-f0-decisiones.md``):

- Los dos archivos tienen el mismo formato y se leen con el lector de DEV04. El control se
  distingue por su ``source_id``, que no puede coincidir con el del conteo principal.
- Se emparejan por **ventana temporal exacta** (mismo inicio y mismo fin), por movimiento y por
  clase. Una ventana que existe en un solo archivo queda sin pareja; una ventana con la matriz
  incompleta en cualquiera de los dos es «no comparable». Nada se descarta en silencio.
- ``error absoluto = observado menos control`` (con signo; también se informa su valor absoluto).
  ``error relativo = |observado menos control| / control``; con control cero es nulo y lleva su
  motivo.

Los valores son exactos: el redondeo se aplica solo al mostrar un reporte.
"""

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from semaforo.datos.importer import CountRow, CountsFile, read_counts
from semaforo.dominio.case import Case
from semaforo.dominio.errors import DomainError, ErrorCode

__all__ = [
    "ZERO_CONTROL_REASON",
    "CountComparison",
    "Exclusion",
    "QualityComparison",
    "QualityError",
    "WindowComparison",
    "compare_files",
    "compare_with_control",
    "find_exclusions",
]

ZERO_CONTROL_REASON = "control cero"
WindowStatus = Literal["comparable", "only_observed", "only_control", "not_comparable"]
Window = tuple[datetime, datetime]


class QualityError(DomainError):
    """Los archivos no se pueden comparar. El código es INPUT_SCHEMA."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(ErrorCode.INPUT_SCHEMA, message, field)


@dataclass(frozen=True)
class CountComparison:
    """Un movimiento y una clase en una ventana comparable, con sus errores."""

    movement_id: str
    vehicle_class: str
    observed: int
    control: int
    absolute_error: int
    relative_error: float | None
    relative_reason: str | None

    @property
    def absolute_value(self) -> int:
        return abs(self.absolute_error)


@dataclass(frozen=True)
class WindowComparison:
    """Una ventana temporal: su estado, su motivo y, si es comparable, sus comparaciones."""

    start: datetime
    end: datetime
    observed_id: str | None
    control_id: str | None
    control_source_id: str | None
    status: WindowStatus
    reason: str | None
    counts: tuple[CountComparison, ...]


@dataclass(frozen=True)
class QualityComparison:
    """Comparación completa, con la huella de cada archivo del que salió."""

    case_id: str
    observed_sha256: str
    control_sha256: str
    windows: tuple[WindowComparison, ...]


@dataclass(frozen=True)
class _Period:
    observation_id: str
    source_ids: frozenset[str]
    counts: dict[tuple[str, str], int]


def compare_files(observed_path: Path, control_path: Path, case: Case) -> QualityComparison:
    """Lee los dos archivos frente a ``case`` y los compara.

    Raises:
        CountImportError: si alguno de los dos archivos no es válido (ver ``read_counts``).
        QualityError: si no se pueden comparar (ver ``compare_with_control``).
    """
    return compare_with_control(
        read_counts(observed_path, case), read_counts(control_path, case), case
    )


def compare_with_control(
    observed: CountsFile, control: CountsFile, case: Case
) -> QualityComparison:
    """Compara dos archivos ya validados frente a ``case``.

    Raises:
        QualityError: si el control comparte alguna fuente con el conteo principal, o si un archivo
            tiene dos periodos con la misma ventana (el emparejamiento sería ambiguo).
    """
    shared = _sources(observed) & _sources(control)
    if shared:
        raise QualityError(
            f"el control comparte la fuente {sorted(shared)} con el conteo principal; "
            "debe ser un conteo independiente con otro source_id",
            "source_id",
        )
    mine = _periods(observed, "principal")
    theirs = _periods(control, "de control")
    expected = [(m.id, vclass) for m in case.movements for vclass in case.vehicle_classes]
    windows = [
        _window(window, mine.get(window), theirs.get(window), expected)
        for window in sorted(mine.keys() | theirs.keys())
    ]
    return QualityComparison(
        case_id=case.case_id,
        observed_sha256=observed.sha256,
        control_sha256=control.sha256,
        windows=tuple(windows),
    )


def _sources(counts: CountsFile) -> set[str]:
    return {row.source_id for row in counts.rows}


def _periods(counts: CountsFile, label: str) -> dict[Window, _Period]:
    by_window: dict[Window, list[CountRow]] = {}
    for row in counts.rows:
        by_window.setdefault((row.start, row.end), []).append(row)
    periods: dict[Window, _Period] = {}
    for window, rows in by_window.items():
        ids = {row.observation_id for row in rows}
        if len(ids) > 1:
            raise QualityError(
                f"el conteo {label} tiene {len(ids)} periodos con la misma ventana "
                f"{window[0].isoformat()} a {window[1].isoformat()} ({sorted(ids)}); "
                "no se puede emparejar con el otro",
                "observation_id",
            )
        periods[window] = _Period(
            observation_id=rows[0].observation_id,
            source_ids=frozenset(row.source_id for row in rows),
            counts={(row.movement_id, row.vehicle_class): row.count for row in rows},
        )
    return periods


def _window(
    window: Window,
    observed: _Period | None,
    control: _Period | None,
    expected: list[tuple[str, str]],
) -> WindowComparison:
    start, end = window
    ids = {
        "observed_id": None if observed is None else observed.observation_id,
        "control_id": None if control is None else control.observation_id,
        "control_source_id": None if control is None else _one(control.source_ids),
    }
    if control is None:
        return WindowComparison(start, end, **ids, status="only_observed", reason=None, counts=())
    if observed is None:
        return WindowComparison(start, end, **ids, status="only_control", reason=None, counts=())
    gaps = _gaps(observed, control, expected)
    if gaps:
        return WindowComparison(start, end, **ids, status="not_comparable", reason=gaps, counts=())
    counts = tuple(
        _count(
            movement, vclass, observed.counts[movement, vclass], control.counts[movement, vclass]
        )
        for movement, vclass in expected
    )
    return WindowComparison(start, end, **ids, status="comparable", reason=None, counts=counts)


def _one(source_ids: frozenset[str]) -> str:
    """La fuente del periodo; si hubiera varias, se informan todas, ordenadas."""
    return ", ".join(sorted(source_ids))


def _gaps(observed: _Period, control: _Period, expected: list[tuple[str, str]]) -> str | None:
    parts: list[str] = []
    for label, period in (("principal", observed), ("de control", control)):
        missing = [key for key in expected if key not in period.counts]
        if missing:
            listed = ", ".join(f"{movement}/{vclass}" for movement, vclass in missing)
            parts.append(f"al conteo {label} le faltan: {listed}")
    return "; ".join(parts) or None


def _count(movement: str, vclass: str, observed: int, control: int) -> CountComparison:
    difference = observed - control
    if control == 0:
        return CountComparison(
            movement, vclass, observed, control, difference, None, ZERO_CONTROL_REASON
        )
    return CountComparison(
        movement, vclass, observed, control, difference, abs(difference) / control, None
    )


@dataclass(frozen=True)
class Exclusion:
    """Una comparación que supera el límite de error y por la que se excluye su ventana."""

    observed_id: str | None
    start: datetime
    end: datetime
    movement_id: str
    vehicle_class: str
    relative_error: float
    threshold: float
    reason: str


def find_exclusions(
    comparison: QualityComparison, max_relative_error: float | None = None
) -> tuple[Exclusion, ...]:
    """Comparaciones que superan ``max_relative_error`` (D5 del acta de F0).

    Sin límite no se excluye nada: la herramienta solo informa. El límite es estricto: un error
    igual al límite no excluye. Un error relativo nulo (control cero) no se puede evaluar contra un
    límite relativo y no excluye; sigue visible en la comparación con su motivo. Solo se evalúan las
    ventanas comparables. Cada exclusión lleva el valor que la causó.

    Raises:
        QualityError: si el límite no es un número finito no negativo.
    """
    if max_relative_error is None:
        return ()
    if not (math.isfinite(max_relative_error) and max_relative_error >= 0):
        raise QualityError(
            "el límite de error relativo debe ser un número finito no negativo",
            "max_relative_error",
        )
    return tuple(
        Exclusion(
            observed_id=window.observed_id,
            start=window.start,
            end=window.end,
            movement_id=count.movement_id,
            vehicle_class=count.vehicle_class,
            relative_error=count.relative_error,
            threshold=max_relative_error,
            reason=(
                f"el error relativo {count.relative_error:.3f} de {count.movement_id}/"
                f"{count.vehicle_class} supera el límite {max_relative_error:g}"
            ),
        )
        for window in comparison.windows
        if window.status == "comparable"
        for count in window.counts
        if count.relative_error is not None and count.relative_error > max_relative_error
    )
