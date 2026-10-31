"""Cobertura temporal y faltantes de los aforos (DEV05 F2, HU03; decisiones D4 y D5).

- **Cobertura = segundos de la ventana de estudio con datos completos ÷ segundos de la ventana.**
  Un periodo cuenta solo si está completo (todos los movimientos y clases del caso). Dos periodos
  que se pisan no cuentan dos veces: se toma la unión de sus intervalos. Los tramos de la ventana
  sin datos completos se informan como huecos.
- La cobertura por movimiento usa la misma regla, pero con la matriz completa **de ese
  movimiento** (todas sus clases).
- La **ventana de estudio** es un parámetro. Si no se da, va del inicio del primer periodo al fin
  del último, y el resultado indica que fue deducida, no declarada.
- Un **límite mínimo de cobertura** es un veredicto sobre la ventana (y sobre cada movimiento),
  no la exclusión de periodos: la cobertura es una propiedad de todo el tiempo de estudio. Sin
  límite no se emite veredicto.
- Los **faltantes** se listan por periodo, movimiento y clase. Nunca se cuentan como cero.
"""

import math
from dataclasses import dataclass
from datetime import datetime

from semaforo.datos.normalizer import PeriodCounts, PreparedCounts
from semaforo.datos.quality import QualityError
from semaforo.dominio.case import Case

__all__ = [
    "Coverage",
    "Gap",
    "MissingEntry",
    "MovementCoverage",
    "assess_coverage",
    "list_missing",
]

Interval = tuple[datetime, datetime]


@dataclass(frozen=True)
class Gap:
    """Un tramo de la ventana de estudio sin datos completos."""

    start: datetime
    end: datetime


@dataclass(frozen=True)
class MovementCoverage:
    """Cobertura de un movimiento; ``meets_minimum`` es None si no se dio un límite."""

    movement_id: str
    covered_s: float
    coverage: float
    meets_minimum: bool | None


@dataclass(frozen=True)
class Coverage:
    """Cobertura de la ventana de estudio, con sus huecos, solapes y periodos fuera de ella."""

    window_start: datetime
    window_end: datetime
    window_declared: bool
    window_s: float
    covered_s: float
    coverage: float
    meets_minimum: bool | None
    gaps: tuple[Gap, ...]
    per_movement: tuple[MovementCoverage, ...]
    overlaps: tuple[tuple[str, str], ...]
    outside_window: tuple[str, ...]


@dataclass(frozen=True)
class MissingEntry:
    """Una combinación de movimiento y clase que falta en un periodo."""

    observation_id: str
    start: datetime
    end: datetime
    movement_id: str
    vehicle_class: str


def list_missing(prepared: PreparedCounts) -> tuple[MissingEntry, ...]:
    """Los faltantes de todos los periodos incompletos, en orden de periodo."""
    return tuple(
        MissingEntry(period.observation_id, period.start, period.end, movement, vclass)
        for period in prepared.periods
        for movement, vclass in period.missing
    )


def assess_coverage(
    prepared: PreparedCounts,
    case: Case,
    window: Interval | None = None,
    min_coverage: float | None = None,
) -> Coverage:
    """Cobertura de ``prepared`` sobre ``window`` (o sobre la ventana deducida de los periodos).

    Raises:
        QualityError: si la ventana es vacía o inversa, si no hay ventana ni periodos de los que
            deducirla, o si ``min_coverage`` no está entre 0 y 1.
    """
    if min_coverage is not None and not (math.isfinite(min_coverage) and 0 <= min_coverage <= 1):
        raise QualityError("el límite mínimo de cobertura debe estar entre 0 y 1", "min_coverage")
    declared = window is not None
    start, end = window if window is not None else _deduced(prepared.periods)
    if end <= start:
        raise QualityError("la ventana de estudio debe terminar después de empezar", "window")
    window_s = (end - start).total_seconds()
    total = _covered([p for p in prepared.periods if not p.missing], (start, end))
    per_movement = tuple(
        _movement(movement.id, prepared.periods, (start, end), window_s, min_coverage)
        for movement in case.movements
    )
    covered_s = _seconds(total)
    coverage = covered_s / window_s
    return Coverage(
        window_start=start,
        window_end=end,
        window_declared=declared,
        window_s=window_s,
        covered_s=covered_s,
        coverage=coverage,
        meets_minimum=None if min_coverage is None else coverage >= min_coverage,
        gaps=tuple(Gap(a, b) for a, b in _gaps((start, end), total)),
        per_movement=per_movement,
        overlaps=_overlaps(prepared.periods),
        outside_window=tuple(
            p.observation_id for p in prepared.periods if p.end <= start or p.start >= end
        ),
    )


def _deduced(periods: tuple[PeriodCounts, ...]) -> Interval:
    if not periods:
        raise QualityError(
            "no hay periodos de los que deducir la ventana de estudio; indique una ventana",
            "window",
        )
    return min(p.start for p in periods), max(p.end for p in periods)


def _movement(
    movement_id: str,
    periods: tuple[PeriodCounts, ...],
    window: Interval,
    window_s: float,
    min_coverage: float | None,
) -> MovementCoverage:
    complete = [p for p in periods if all(m != movement_id for m, _ in p.missing)]
    covered_s = _seconds(_covered(complete, window))
    coverage = covered_s / window_s
    return MovementCoverage(
        movement_id=movement_id,
        covered_s=covered_s,
        coverage=coverage,
        meets_minimum=None if min_coverage is None else coverage >= min_coverage,
    )


def _covered(periods: list[PeriodCounts], window: Interval) -> list[Interval]:
    """Unión de los intervalos de ``periods``, recortada a ``window``."""
    clipped = [
        (max(p.start, window[0]), min(p.end, window[1]))
        for p in periods
        if p.start < window[1] and p.end > window[0]
    ]
    merged: list[Interval] = []
    for start, end in sorted(clipped):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _seconds(intervals: list[Interval]) -> float:
    return sum((end - start).total_seconds() for start, end in intervals)


def _gaps(window: Interval, covered: list[Interval]) -> list[Interval]:
    gaps: list[Interval] = []
    cursor = window[0]
    for start, end in covered:
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < window[1]:
        gaps.append((cursor, window[1]))
    return gaps


def _overlaps(periods: tuple[PeriodCounts, ...]) -> tuple[tuple[str, str], ...]:
    ordered = sorted(periods, key=lambda p: (p.start, p.end, p.observation_id))
    pairs: list[tuple[str, str]] = []
    for index, first in enumerate(ordered):
        for second in ordered[index + 1 :]:
            if second.start >= first.end:
                break
            pairs.append((first.observation_id, second.observation_id))
    return tuple(pairs)
