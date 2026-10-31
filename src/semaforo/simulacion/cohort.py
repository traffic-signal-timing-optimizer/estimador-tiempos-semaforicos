"""Cohorte de vehículos de un escenario (DEV06 F1, HU04; decisiones D5 a D9 y D17 de F0).

Dado un escenario y su caso, produce la lista exacta de vehículos que se simularán: un
identificador, el movimiento, la clase y la hora de salida de cada uno. La misma lista se reutiliza
entre las alternativas de semáforo, así que se compara con exactamente los mismos vehículos. Las
rutas y los tipos se agregan al materializar las entradas de SUMO (F2).

- **Cuántos.** Por movimiento: ``flujo * tiempo / 3600``, redondeado al entero más cercano (la
  mitad sube). El reparto entre clases usa el método del mayor resto, así que la suma es exacta;
  en un empate gana la clase de menor identificador. Una clase con proporción 0 tiene 0 vehículos.
- **Cuándo salen.** Horas uniformes al azar dentro de la ventana, llevadas hacia abajo a un
  múltiplo del tick del caso, así que ninguna sale de su ventana. Cada movimiento y cada ventana
  (calentamiento y medición) tiene su propia semilla, derivada con SHA-256 de la semilla de la
  demanda, el movimiento y la ventana: agregar un movimiento o cambiar el calentamiento no cambia
  los vehículos de los demás.
- **Calentamiento.** Se genera también demanda de 0 a ``warmup_s``. Esos vehículos se simulan pero
  no son cohorte. La cohorte son los que salen en ``[warmup_s, warmup_s + measure_s)``.
- **Identificadores.** ``<movimiento>.<clase>.<n>`` y, en el calentamiento,
  ``<movimiento>.cal.<clase>.<n>``, con ``n`` desde 1 en el orden de salida. Movimientos y clases
  solo pueden tener letras, números, guion bajo y guion, así que el punto separa sin ambigüedad.

No lee ni escribe archivos. Mismos insumos y semilla dan siempre la misma lista.
"""

import hashlib
import math
import random
import re
from dataclasses import dataclass
from fractions import Fraction

from semaforo.dominio.case import Case
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.dominio.scenario import Scenario, ScenarioInvalidError, scenario_issues

__all__ = [
    "MAX_VEHICLES",
    "Cohort",
    "CohortCount",
    "CohortError",
    "CohortVehicle",
    "generate_cohort",
]

MAX_VEHICLES = 200_000
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
WARMUP_TAG = "cal"
SECONDS_PER_HOUR = 3600
WARMUP_PHASE = "calentamiento"
MEASURE_PHASE = "medicion"


class CohortError(DomainError):
    """No se puede generar la cohorte: identificadores inseguros o demasiados vehículos."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(ErrorCode.INPUT_SCHEMA, message, field)


@dataclass(frozen=True)
class _Window:
    """Ventana de generación: el calentamiento o la medición, en segundos desde el inicio."""

    phase: str
    start_s: float
    end_s: float


@dataclass(frozen=True)
class CohortVehicle:
    """Un vehículo pedido. ``in_cohort`` es falso para los del calentamiento."""

    vehicle_id: str
    movement_id: str
    vehicle_class: str
    depart_s: float
    in_cohort: bool


@dataclass(frozen=True)
class CohortCount:
    """Cuántos vehículos se pidieron de un movimiento y una clase."""

    movement_id: str
    vehicle_class: str
    warmup: int
    measured: int


@dataclass(frozen=True)
class Cohort:
    """Vehículos ordenados por hora de salida (y luego por identificador), con sus conteos."""

    vehicles: tuple[CohortVehicle, ...]
    counts: tuple[CohortCount, ...]

    @property
    def measured(self) -> tuple[CohortVehicle, ...]:
        """Los vehículos de la cohorte (sin los del calentamiento)."""
        return tuple(vehicle for vehicle in self.vehicles if vehicle.in_cohort)


def generate_cohort(scenario: Scenario, case: Case, max_vehicles: int = MAX_VEHICLES) -> Cohort:
    """La cohorte del escenario sobre el caso.

    Raises:
        ScenarioInvalidError: si el escenario no encaja con el caso.
        CohortError: si algún movimiento o clase tiene un identificador inseguro, o si los
            vehículos pedidos superan ``max_vehicles``.
    """
    issues = scenario_issues(scenario, case)
    if issues:
        raise ScenarioInvalidError(issues)
    _check_identifiers(case)
    plan = _plan(scenario, case)
    total = sum(count.warmup + count.measured for count in plan)
    if total > max_vehicles:
        raise CohortError(
            f"el escenario pide {total} vehículos y el máximo permitido es {max_vehicles}"
        )
    windows = (
        _Window(WARMUP_PHASE, 0.0, scenario.warmup_s),
        _Window(MEASURE_PHASE, scenario.warmup_s, scenario.warmup_s + scenario.measure_s),
    )
    vehicles: list[CohortVehicle] = []
    for row in scenario.request.demand:
        counts = [count for count in plan if count.movement_id == row.movement_id]
        for window in windows:
            vehicles += _movement_vehicles(
                scenario.demand_seed, case.tick_s, row.movement_id, counts, window
            )
    vehicles.sort(key=lambda vehicle: (vehicle.depart_s, vehicle.vehicle_id))
    return Cohort(tuple(vehicles), tuple(plan))


def _check_identifiers(case: Case) -> None:
    for index, movement in enumerate(case.movements):
        if SAFE_ID.fullmatch(movement.id) is None:
            raise CohortError(
                f"el movimiento «{movement.id}» solo puede tener letras, números, "
                "guion bajo y guion",
                f"movements[{index}].id",
            )
    for index, name in enumerate(case.vehicle_classes):
        if SAFE_ID.fullmatch(name) is None:
            raise CohortError(
                f"la clase «{name}» solo puede tener letras, números, guion bajo y guion",
                f"vehicle_classes[{index}]",
            )


def _decimal(value: float) -> Fraction:
    """El número como lo escribió quien lo dio (0.1 es un décimo, no su aproximación binaria)."""
    return Fraction(repr(float(value)))


def _plan(scenario: Scenario, case: Case) -> list[CohortCount]:
    """Cuántos vehículos de cada movimiento y clase, en el orden de la demanda y de las clases."""
    plan: list[CohortCount] = []
    for row in scenario.request.demand:
        warmup = _split(row.flow_vph, scenario.warmup_s, row.composition)
        measured = _split(row.flow_vph, scenario.measure_s, row.composition)
        plan.extend(
            CohortCount(row.movement_id, name, warmup.get(name, 0), measured.get(name, 0))
            for name in sorted(case.vehicle_classes)
        )
    return plan


def _split(flow_vph: float, seconds: float, composition: dict[str, float] | None) -> dict[str, int]:
    """Vehículos por clase: total redondeado al más cercano y reparto por mayor resto."""
    exact = _decimal(flow_vph) * _decimal(seconds) / SECONDS_PER_HOUR
    total = math.floor(exact + Fraction(1, 2))
    if total == 0 or composition is None:
        return {}
    # Se divide por la suma de las proporciones para que las partes sumen exactamente el total
    # (la suma puede apartarse de 1 dentro de la tolerancia del escenario).
    weight = sum(_decimal(share) for share in composition.values())
    shares = {name: total * _decimal(share) / weight for name, share in composition.items()}
    counts = {name: math.floor(share) for name, share in shares.items()}
    # Mayor parte decimal primero; en un empate, el menor identificador.
    order = sorted(shares, key=lambda name: (-(shares[name] - counts[name]), name))
    for name in order[: total - sum(counts.values())]:
        counts[name] += 1
    return counts


def _stream(seed: int, movement_id: str, phase: str) -> random.Random:
    """Generador propio de un movimiento y una ventana, derivado de la semilla de la demanda."""
    digest = hashlib.sha256(f"{seed}|{movement_id}|{phase}".encode()).digest()
    return random.Random(int.from_bytes(digest, "big"))  # noqa: S311 - simulación, no seguridad


def _movement_vehicles(
    seed: int, tick: float, movement_id: str, counts: list[CohortCount], window: _Window
) -> list[CohortVehicle]:
    """Los vehículos de un movimiento en una ventana (calentamiento o medición)."""
    in_cohort = window.phase == MEASURE_PHASE
    per_class = {
        count.vehicle_class: (count.measured if in_cohort else count.warmup) for count in counts
    }
    total = sum(per_class.values())
    rng = _stream(seed, movement_id, window.phase)
    start_tick = round(window.start_s / tick)
    span_ticks = round((window.end_s - window.start_s) / tick)
    # Las horas se sortean primero y las clases se reparten con una permutación propia.
    ticks = sorted(
        start_tick + min(int(rng.random() * span_ticks), span_ticks - 1) for _ in range(total)
    )
    classes = [name for name in sorted(per_class) for _ in range(per_class[name])]
    for position in range(len(classes) - 1, 0, -1):
        other = int(rng.random() * (position + 1))
        classes[position], classes[other] = classes[other], classes[position]
    served: dict[str, int] = {}
    vehicles: list[CohortVehicle] = []
    for tick_index, name in zip(ticks, classes, strict=True):
        served[name] = served.get(name, 0) + 1
        tag = "" if in_cohort else f"{WARMUP_TAG}."
        vehicles.append(
            CohortVehicle(
                f"{movement_id}.{tag}{name}.{served[name]}",
                movement_id,
                name,
                round(tick_index * tick, 6),
                in_cohort,
            )
        )
    return vehicles
