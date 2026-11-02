"""Cola y detenciones en la zona de medición (DEV19 F3; decisiones D9 a D11 de F0; QA27).

Definiciones del protocolo, con los parámetros del contrato ``protocol``:

- **Cola:** en cada tick de muestreo ``inicio + k · queue_sampling_s`` dentro del intervalo de
  medición [inicio, fin), los vehículos (todos, también los de calentamiento) que están en un
  carril de ``zone_lane_ids`` con velocidad ≤ ``queue_speed_threshold_mps``. Se informa la media
  en el tiempo, el máximo y la suma (veh·tick), en total y por acceso. Un tick sin vehículos
  cuenta 0; un tick que **falta** en la FCD no se rellena: la cobertura baja y la cola queda
  ``incomplete``, sin valores. Cada vehículo está en un solo carril por paso, así que nadie se
  cuenta dos veces.
- **Detención:** de un vehículo de la cohorte, dentro de la zona y en toda la corrida, el paso de
  velocidad > ``stop_speed_threshold_mps`` a ≤ ese umbral entre dos pasos seguidos. **Estado
  inicial:** un vehículo que aparece en la zona ya detenido (sin registro en el paso anterior)
  cuenta una detención. El total se divide entre los N solicitados: es la media si la cohorte del
  grupo terminó y una cota inferior si está censurada (los que seguían en la red podían detenerse
  más).

El acceso de un carril es el del movimiento que entra por él (``approach_id``); un carril de la
zona que no es de ningún movimiento usa el nombre de su calle.
"""

import math
from pathlib import Path
from typing import Literal

from pydantic import Field

from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.case import Case
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.dominio.protocol import Protocol
from semaforo.evaluacion.cohort import CohortDelay, DelayStatus, DelaySummary
from semaforo.evaluacion.errors import EvaluacionError
from semaforo.evaluacion.fcd import FcdRecord, read_fcd

__all__ = [
    "MAX_FCD_BYTES",
    "QueueStatus",
    "QueueSummary",
    "StopsSummary",
    "ZoneMetrics",
    "ZoneSettings",
    "lane_access",
    "zone_metrics",
]

# Mismo tope que el de las salidas de una corrida (DEV07): la FCD es una de ellas.
MAX_FCD_BYTES = 512 * 1024 * 1024
# Tolerancia para reconocer un tick en tiempos escritos con dos decimales (s).
TICK_TOLERANCE_S = 1e-6
QueueStatus = Literal["complete", "incomplete", "empty"]


class QueueSummary(FrozenModel):
    """Cola de un grupo (toda la zona o un acceso), en vehículos detenidos por tick.

    ``coverage`` = ticks presentes / ticks esperados. Con un tick faltante la cola es
    ``incomplete`` y no lleva valores; sin ticks esperados es ``empty``.
    """

    status: QueueStatus
    ticks_expected: int = Field(ge=0)
    ticks_observed: int = Field(ge=0)
    coverage: float | None
    vehicle_ticks: int | None
    mean_vehicles: float | None
    max_vehicles: int | None


class StopsSummary(FrozenModel):
    """Detenciones de un grupo de la cohorte. ``requested`` es el denominador: todos los pedidos.

    ``total_stops`` es lo observado; la media existe si el grupo es ``complete`` y la cota
    inferior si es ``censored``.
    """

    requested: int = Field(ge=0)
    status: DelayStatus
    total_stops: int = Field(ge=0)
    mean_stops: float | None
    lower_bound_mean_stops: float | None


class ZoneSettings(FrozenModel):
    """Con qué se midió: lo del protocolo y los tiempos de la corrida (s y m/s)."""

    zone_lane_ids: list[str]
    queue_speed_threshold_mps: float
    stop_speed_threshold_mps: float
    queue_sampling_s: float
    step_length_s: float
    measure_start_s: float
    measure_end_s: float


class ZoneMetrics(FrozenModel):
    """Cola y detenciones de una corrida, total y por acceso, y detenciones por vehículo."""

    settings: ZoneSettings
    queue: QueueSummary
    queue_by_access: dict[str, QueueSummary]
    stops: StopsSummary
    stops_by_access: dict[str, StopsSummary]
    vehicle_stops: dict[str, int]
    fcd_steps: int = Field(ge=0)


def lane_access(case: Case, lanes: list[str]) -> dict[str, str]:
    """Acceso de cada carril: el ``approach_id`` del movimiento que entra por él o, si no es de
    ninguno, el nombre de su calle (el carril sin su ``_<índice>`` final).
    """
    declared = {
        lane: movement.approach_id
        for movement in case.movements
        for lane in movement.incoming_lanes
    }
    return {lane: declared.get(lane, lane.rsplit("_", 1)[0]) for lane in lanes}


def _sample_ticks(start_s: float, end_s: float, sampling_s: float, step_s: float) -> int:
    """Ticks de muestreo esperados en [inicio, fin). El muestreo debe ser múltiplo del paso.

    Raises:
        EvaluacionError: INPUT_SCHEMA si el muestreo no es un múltiplo entero del paso.
    """
    ratio = sampling_s / step_s
    steps = round(ratio)
    if steps < 1 or abs(ratio - steps) > TICK_TOLERANCE_S:
        raise EvaluacionError(
            ErrorCode.INPUT_SCHEMA,
            f"el muestreo de la cola ({sampling_s:g} s) no es un múltiplo del paso ({step_s:g} s)",
            "queue_sampling_s",
        )
    return max(0, math.ceil((end_s - start_s) / sampling_s - TICK_TOLERANCE_S))


class _Accumulator:
    """Lo que se va sumando paso a paso. La memoria crece con los vehículos, no con la FCD."""

    def __init__(self, access: dict[str, str], cohort: set[str], settings: ZoneSettings) -> None:
        self.access = access
        self.cohort = cohort
        self.settings = settings
        names = sorted(set(access.values()))
        self.queue_sum = dict.fromkeys(names, 0)
        self.queue_max = dict.fromkeys(names, 0)
        self.total_sum = 0
        self.total_max = 0
        self.observed: set[int] = set()
        self.stops = dict.fromkeys(sorted(cohort), 0)
        self.last: dict[str, tuple[float, bool]] = {}

    def _sample_index(self, time: float) -> int | None:
        settings = self.settings
        early = time < settings.measure_start_s - TICK_TOLERANCE_S
        if early or time >= settings.measure_end_s - TICK_TOLERANCE_S:
            return None
        position = (time - settings.measure_start_s) / settings.queue_sampling_s
        index = round(position)
        return index if abs(position - index) <= TICK_TOLERANCE_S else None

    def step(self, time: float, records: list[FcdRecord]) -> None:
        inside = [record for record in records if record.lane in self.access]
        index = self._sample_index(time)
        if index is not None:
            self._queue(index, inside)
        for record in inside:
            if record.vehicle_id in self.cohort:
                self._stop(time, record)

    def _queue(self, index: int, inside: list[FcdRecord]) -> None:
        self.observed.add(index)
        threshold = self.settings.queue_speed_threshold_mps
        counts = dict.fromkeys(self.queue_sum, 0)
        for record in inside:
            if record.speed_mps <= threshold:
                counts[self.access[record.lane]] += 1
        for name, count in counts.items():
            self.queue_sum[name] += count
            self.queue_max[name] = max(self.queue_max[name], count)
        total = sum(counts.values())
        self.total_sum += total
        self.total_max = max(self.total_max, total)

    def _stop(self, time: float, record: FcdRecord) -> None:
        stopped = record.speed_mps <= self.settings.stop_speed_threshold_mps
        previous = self.last.get(record.vehicle_id)
        follows = (
            previous is not None
            and abs(time - previous[0] - self.settings.step_length_s) <= TICK_TOLERANCE_S
        )
        if stopped and not (follows and previous is not None and previous[1]):
            self.stops[record.vehicle_id] += 1
        self.last[record.vehicle_id] = (time, stopped)


def _queue_summary(expected: int, observed: int, total: int, peak: int) -> QueueSummary:
    if expected == 0:
        return QueueSummary(
            status="empty",
            ticks_expected=0,
            ticks_observed=0,
            coverage=None,
            vehicle_ticks=None,
            mean_vehicles=None,
            max_vehicles=None,
        )
    complete = observed == expected
    return QueueSummary(
        status="complete" if complete else "incomplete",
        ticks_expected=expected,
        ticks_observed=observed,
        coverage=observed / expected,
        vehicle_ticks=total if complete else None,
        mean_vehicles=total / expected if complete else None,
        max_vehicles=peak if complete else None,
    )


def _stops_summary(group: DelaySummary, total: int) -> StopsSummary:
    mean = None if group.requested == 0 else total / group.requested
    return StopsSummary(
        requested=group.requested,
        status=group.status,
        total_stops=total,
        mean_stops=mean if group.status == "complete" else None,
        lower_bound_mean_stops=mean if group.status == "censored" else None,
    )


def zone_metrics(  # noqa: PLR0913  (los tiempos de la corrida son de solo palabra clave)
    fcd: Path,
    protocol: Protocol,
    case: Case,
    cohort: CohortDelay,
    *,
    step_s: float,
    start_s: float,
    end_s: float,
    max_bytes: int = MAX_FCD_BYTES,
) -> ZoneMetrics:
    """Cola y detenciones de una corrida a partir de su ``fcd.xml``.

    Args:
        fcd: la FCD de la corrida (``outputs/fcd.xml``).
        protocol: da la zona, los umbrales y el muestreo.
        case: el caso de la corrida, para el acceso de cada carril.
        cohort: la demora de la cohorte de la misma corrida (F2): da los vehículos, su acceso y si
            cada grupo terminó.
        step_s: paso de la simulación (s).
        start_s, end_s: intervalo de medición de la cola [inicio, fin), en s.
        max_bytes: tope de la FCD descomprimida.

    Raises:
        EvaluacionError: INPUT_SCHEMA si el muestreo no es múltiplo del paso; OUTPUT_INVALID si la
            FCD no se puede leer o no es válida.
    """
    access = lane_access(case, protocol.zone_lane_ids)
    vehicles = {vehicle.vehicle_id: vehicle.access_id for vehicle in cohort.vehicles}
    expected = _sample_ticks(start_s, end_s, protocol.queue_sampling_s, step_s)
    settings = ZoneSettings(
        zone_lane_ids=list(protocol.zone_lane_ids),
        queue_speed_threshold_mps=protocol.queue_speed_threshold_mps,
        stop_speed_threshold_mps=protocol.stop_speed_threshold_mps,
        queue_sampling_s=protocol.queue_sampling_s,
        step_length_s=step_s,
        measure_start_s=start_s,
        measure_end_s=end_s,
    )
    accumulator = _Accumulator(access, set(vehicles), settings)
    try:
        steps = read_fcd(fcd, max_bytes, accumulator.step)
    except DomainError as error:
        raise EvaluacionError(ErrorCode.OUTPUT_INVALID, error.message, fcd.name) from error
    observed = len(accumulator.observed)
    by_access_stops: dict[str, int] = dict.fromkeys(sorted(cohort.by_access), 0)
    for vehicle_id, count in accumulator.stops.items():
        by_access_stops[vehicles[vehicle_id]] += count
    return ZoneMetrics(
        settings=settings,
        queue=_queue_summary(expected, observed, accumulator.total_sum, accumulator.total_max),
        queue_by_access={
            name: _queue_summary(
                expected, observed, accumulator.queue_sum[name], accumulator.queue_max[name]
            )
            for name in accumulator.queue_sum
        },
        stops=_stops_summary(cohort.total, sum(accumulator.stops.values())),
        stops_by_access={
            name: _stops_summary(cohort.by_access[name], count)
            for name, count in by_access_stops.items()
        },
        vehicle_stops=dict(accumulator.stops),
        fcd_steps=steps,
    )
