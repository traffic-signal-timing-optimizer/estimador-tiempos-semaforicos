"""Normalización de aforos a veh/h y proporciones por clase (DEV04, HU02).

Para cada periodo y cada movimiento del caso:

- ``flujo (veh/h) = 3600 por total de vehículos, dividido entre la duración en segundos``; con cero
  vehículos el flujo es 0, no un faltante.
- ``proporción de la clase = conteo de la clase / total del movimiento``; con cero vehículos la
  composición es ``None`` (no existe proporción que informar).

La matriz de cada periodo es completa: todas las combinaciones de movimiento y clase del caso. Si
falta una, el periodo queda ``incomplete``: no tiene flujos ni composiciones, y la lista de
faltantes dice cuáles son. Un faltante nunca se convierte en cero.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from semaforo.datos.importer import CountRow, CountsFile, read_counts
from semaforo.dominio.case import Case

__all__ = [
    "MovementFlow",
    "PeriodCounts",
    "PreparedCounts",
    "normalize",
    "prepare_counts",
]

SECONDS_PER_HOUR = 3600


@dataclass(frozen=True)
class MovementFlow:
    """Flujo de un movimiento en un periodo completo, y la proporción de cada clase."""

    movement_id: str
    flow_vph: float
    composition: Mapping[str, float | None]


@dataclass(frozen=True)
class PeriodCounts:
    """Un periodo de observación.

    ``status`` es ``incomplete`` si falta alguna combinación de movimiento y clase; en ese caso
    ``movements`` está vacío y ``missing`` dice cuáles faltan. No debe usarse para inferencia.
    """

    observation_id: str
    start: datetime
    end: datetime
    duration_s: float
    status: Literal["complete", "incomplete"]
    movements: tuple[MovementFlow, ...]
    missing: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class PreparedCounts:
    """Aforos normalizados del caso, con la huella del archivo original del que salieron."""

    case_id: str
    source_sha256: str
    periods: tuple[PeriodCounts, ...]


def prepare_counts(path: Path, case: Case) -> PreparedCounts:
    """Lee, valida y normaliza el archivo de aforos ``path`` frente a ``case``.

    Raises:
        CountImportError: si el archivo no es válido (ver ``importer.read_counts``).
    """
    return normalize(read_counts(path, case), case)


def normalize(counts: CountsFile, case: Case) -> PreparedCounts:
    """Periodos normalizados de un archivo ya validado."""
    windows: dict[str, list[CountRow]] = {}
    for row in counts.rows:
        windows.setdefault(row.observation_id, []).append(row)
    periods = [_period(observation_id, rows, case) for observation_id, rows in windows.items()]
    periods.sort(key=lambda period: (period.start, period.observation_id))
    return PreparedCounts(
        case_id=counts.case_id, source_sha256=counts.sha256, periods=tuple(periods)
    )


def _period(observation_id: str, rows: list[CountRow], case: Case) -> PeriodCounts:
    first = rows[0]
    duration_s = (first.end - first.start).total_seconds()
    expected = [(m.id, vclass) for m in case.movements for vclass in case.vehicle_classes]
    counted = {(row.movement_id, row.vehicle_class): row.count for row in rows}
    missing = tuple(key for key in expected if key not in counted)
    if missing:
        return PeriodCounts(
            observation_id=observation_id,
            start=first.start,
            end=first.end,
            duration_s=duration_s,
            status="incomplete",
            movements=(),
            missing=missing,
        )
    movements = tuple(
        _movement(m.id, case.vehicle_classes, counted, duration_s) for m in case.movements
    )
    return PeriodCounts(
        observation_id=observation_id,
        start=first.start,
        end=first.end,
        duration_s=duration_s,
        status="complete",
        movements=movements,
        missing=(),
    )


def _movement(
    movement_id: str,
    classes: list[str],
    counted: Mapping[tuple[str, str], int],
    duration_s: float,
) -> MovementFlow:
    per_class = {vclass: counted[(movement_id, vclass)] for vclass in classes}
    total = sum(per_class.values())
    flow = SECONDS_PER_HOUR * total / duration_s
    composition: dict[str, float | None] = {
        vclass: (None if total == 0 else count / total) for vclass, count in per_class.items()
    }
    return MovementFlow(movement_id=movement_id, flow_vph=flow, composition=composition)
