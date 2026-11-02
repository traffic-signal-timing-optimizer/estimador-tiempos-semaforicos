"""Demora de la cohorte y su censura (DEV19 F2; decisiones D5 a D8 y D11 de F0; QA25).

``simulacion/cohort.py`` genera la cohorte (quién se pide); este módulo la **mide** después de la
corrida, a partir de la conciliación de DEV06 y de los viajes de SUMO.

Demora de un vehículo = ``timeLoss`` + ``departDelay`` (protocolo, «Definición propuesta»), con
las dos partes por separado:

- ``finished``: lo que dice SUMO al llegar.
- ``unfinished``: lo acumulado hasta el fin de la simulación (SUMO lo escribe con
  ``write-unfinished``): es una **cota inferior**.
- ``not_inserted``: no tuvo tiempo perdido en ruta; su espera para entrar es la que registra SUMO
  (``write-undeparted``) o, en una corrida sin ese registro, el fin de la simulación menos su
  salida programada. También es una cota inferior.

Si los N solicitados terminaron, la cohorte es ``complete`` y su media es suma / N. Si no, es
``censored``: **no hay media completa**, solo la cota inferior (suma de lo acumulado / N) y los
conteos residuales. Nadie se excluye: cada vehículo de la cohorte está en la tabla y en los
denominadores, por acceso y por movimiento. Nunca se calcula la media de los que terminaron.

``compare_cohorts`` compara dos corridas con la misma cohorte sin esa media sesgada (QA26).
"""

import math
from collections.abc import Iterable, Mapping
from typing import Literal

from pydantic import Field

from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.case import Case
from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.protocol import Protocol
from semaforo.dominio.timing import shown
from semaforo.evaluacion.errors import EvaluacionError
from semaforo.simulacion.reconcile import Reconciliation, Status, VehicleOutcome
from semaforo.simulacion.tripinfo import Trip

__all__ = [
    "CENSORING_POLICY",
    "COHORT_POLICY",
    "CohortComparison",
    "CohortDelay",
    "DelayStatus",
    "DelaySummary",
    "GroupComparison",
    "VehicleDelay",
    "Verdict",
    "cohort_delay",
    "compare_cohorts",
    "require_supported",
    "summarize_delays",
]

# Lo único que esta versión sabe medir (D5). Otra política se rechaza: no se inventa su regla.
COHORT_POLICY = "requested_depart_in_measurement_window"
CENSORING_POLICY = "complete_cohort_or_no_label"
DelayStatus = Literal["complete", "censored", "empty"]
DelaySource = Literal["sumo", "schedule"]


class VehicleDelay(FrozenModel):
    """Demora de un vehículo de la cohorte, en segundos.

    ``depart_delay_source`` dice de dónde sale la espera de un no insertado: ``sumo`` (su
    registro) o ``schedule`` (fin de la simulación menos su salida programada).
    """

    vehicle_id: str
    movement_id: str
    vehicle_class: str
    access_id: str
    status: Status
    time_loss_s: float = Field(ge=0)
    depart_delay_s: float = Field(ge=0)
    depart_delay_source: DelaySource

    @property
    def delay_s(self) -> float:
        return self.time_loss_s + self.depart_delay_s


class DelaySummary(FrozenModel):
    """Demora de un grupo de la cohorte (toda, un acceso o un movimiento).

    - ``requested`` es el denominador: los vehículos pedidos del grupo, todos.
    - Las medias (``mean_*``) existen solo si el grupo es ``complete``.
    - Las cotas inferiores (``lower_bound_mean_*``) existen solo si es ``censored``.
    - ``sum_delay_s`` es la suma de lo medido: completa o cota inferior según ``status``.
    """

    requested: int = Field(ge=0)
    finished: int = Field(ge=0)
    unfinished: int = Field(ge=0)
    not_inserted: int = Field(ge=0)
    status: DelayStatus
    sum_delay_s: float = Field(ge=0)
    mean_delay_s: float | None
    mean_time_loss_s: float | None
    mean_depart_delay_s: float | None
    lower_bound_mean_delay_s: float | None
    lower_bound_mean_time_loss_s: float | None
    lower_bound_mean_depart_delay_s: float | None


class CohortDelay(FrozenModel):
    """Demora de la cohorte de una corrida: total, por acceso, por movimiento y por vehículo.

    ``warmup_vehicles`` se informa aparte: no entra en ningún denominador.
    """

    total: DelaySummary
    by_access: dict[str, DelaySummary]
    by_movement: dict[str, DelaySummary]
    warmup_vehicles: int = Field(ge=0)
    simulation_end_s: float
    vehicles: list[VehicleDelay]


def _error(message: str, field: str | None = None) -> EvaluacionError:
    return EvaluacionError(ErrorCode.OUTPUT_INVALID, message, field)


def require_supported(protocol: Protocol) -> None:
    """Exige una población y una censura que esta versión sabe medir (D5).

    Raises:
        EvaluacionError: INPUT_SCHEMA si el protocolo pide otra cosa.
    """
    if protocol.cohort_policy != COHORT_POLICY:
        raise EvaluacionError(
            ErrorCode.INPUT_SCHEMA,
            f"la población {shown(protocol.cohort_policy)!r} no está admitida; "
            f"se admite {COHORT_POLICY!r}",
            "cohort_policy",
        )
    if protocol.censoring_policy != CENSORING_POLICY:
        raise EvaluacionError(
            ErrorCode.INPUT_SCHEMA,
            f"la censura {shown(protocol.censoring_policy)!r} no está admitida; se admite "
            f"{CENSORING_POLICY!r} (otra regla debe aprobarse y programarse antes)",
            "censoring_policy",
        )


def _measured(trip: Trip, name: str, vehicle_id: str) -> float:
    value = trip.time_loss if name == "timeLoss" else trip.depart_delay
    if value is None:
        raise _error(f"al viaje de {shown(vehicle_id)!r} le falta {name}", "tripinfo.xml")
    if value < 0:
        raise _error(f"el viaje de {shown(vehicle_id)!r} tiene {name} negativo", "tripinfo.xml")
    return value


def _vehicle(
    outcome: VehicleOutcome, trip: Trip | None, access_id: str, end_s: float
) -> VehicleDelay:
    vehicle_id = outcome.vehicle_id
    started = trip is not None and trip.started
    if (outcome.status != "not_inserted") != started:
        raise _error(
            f"la conciliación y los viajes no coinciden para {shown(vehicle_id)!r}", "tripinfo.xml"
        )
    if trip is None or not trip.started:
        if trip is None:
            waited, source = max(0.0, end_s - outcome.scheduled_s), "schedule"
        else:
            waited, source = _measured(trip, "departDelay", vehicle_id), "sumo"
        return VehicleDelay(
            vehicle_id=vehicle_id,
            movement_id=outcome.movement_id,
            vehicle_class=outcome.vehicle_class,
            access_id=access_id,
            status="not_inserted",
            time_loss_s=0.0,
            depart_delay_s=waited,
            depart_delay_source=source,
        )
    return VehicleDelay(
        vehicle_id=vehicle_id,
        movement_id=outcome.movement_id,
        vehicle_class=outcome.vehicle_class,
        access_id=access_id,
        status=outcome.status,
        time_loss_s=_measured(trip, "timeLoss", vehicle_id),
        depart_delay_s=_measured(trip, "departDelay", vehicle_id),
        depart_delay_source="sumo",
    )


def _mean(values: Iterable[float], count: int) -> float:
    return math.fsum(values) / count


def summarize_delays(vehicles: list[VehicleDelay]) -> DelaySummary:
    """Resumen de un grupo: conteos, estado y medias o cotas inferiores (D6 y D7)."""
    requested = len(vehicles)
    counts = {
        status: sum(1 for vehicle in vehicles if vehicle.status == status)
        for status in ("finished", "unfinished", "not_inserted")
    }
    status: DelayStatus = (
        "empty" if requested == 0 else "complete" if counts["finished"] == requested else "censored"
    )
    means = (
        None
        if requested == 0
        else (
            _mean((vehicle.delay_s for vehicle in vehicles), requested),
            _mean((vehicle.time_loss_s for vehicle in vehicles), requested),
            _mean((vehicle.depart_delay_s for vehicle in vehicles), requested),
        )
    )
    complete = means if status == "complete" else None
    bound = means if status == "censored" else None
    return DelaySummary(
        requested=requested,
        finished=counts["finished"],
        unfinished=counts["unfinished"],
        not_inserted=counts["not_inserted"],
        status=status,
        sum_delay_s=math.fsum(vehicle.delay_s for vehicle in vehicles),
        mean_delay_s=None if complete is None else complete[0],
        mean_time_loss_s=None if complete is None else complete[1],
        mean_depart_delay_s=None if complete is None else complete[2],
        lower_bound_mean_delay_s=None if bound is None else bound[0],
        lower_bound_mean_time_loss_s=None if bound is None else bound[1],
        lower_bound_mean_depart_delay_s=None if bound is None else bound[2],
    )


def _grouped(vehicles: list[VehicleDelay], key: str) -> dict[str, DelaySummary]:
    groups: dict[str, list[VehicleDelay]] = {}
    for vehicle in vehicles:
        groups.setdefault(getattr(vehicle, key), []).append(vehicle)
    return {name: summarize_delays(groups[name]) for name in sorted(groups)}


def cohort_delay(
    reconciliation: Reconciliation, trips: Mapping[str, Trip], case: Case, end_s: float
) -> CohortDelay:
    """Demora de la cohorte de una corrida.

    Args:
        reconciliation: la conciliación de la corrida (DEV06), con todos los vehículos pedidos.
        trips: los viajes del ``tripinfo`` de la misma corrida, por identificador.
        case: el caso de la corrida; da el acceso de cada movimiento (``approach_id``).
        end_s: fin de la simulación, en segundos (del manifiesto de las entradas).

    Raises:
        EvaluacionError: OUTPUT_INVALID si un movimiento no es del caso, si la conciliación y los
            viajes no coinciden, o si a un viaje le falta un tiempo o lo tiene negativo.
    """
    access_of = {movement.id: movement.approach_id for movement in case.movements}
    vehicles: list[VehicleDelay] = []
    warmup = 0
    for outcome in reconciliation.outcomes:
        if not outcome.in_cohort:
            warmup += 1
            continue
        access_id = access_of.get(outcome.movement_id)
        if access_id is None:
            raise _error(
                f"el movimiento {shown(outcome.movement_id)!r} no es del caso",
                "cohorte_conciliada.csv",
            )
        vehicles.append(_vehicle(outcome, trips.get(outcome.vehicle_id), access_id, end_s))
    total = summarize_delays(vehicles)
    if (total.requested, total.finished, total.unfinished, total.not_inserted) != (
        reconciliation.requested,
        reconciliation.finished,
        reconciliation.unfinished,
        reconciliation.not_inserted,
    ):
        raise _error("los conteos de la conciliación no son los de sus vehículos", "conciliacion")
    return CohortDelay(
        total=total,
        by_access=_grouped(vehicles, "access_id"),
        by_movement=_grouped(vehicles, "movement_id"),
        warmup_vehicles=warmup,
        simulation_end_s=end_s,
        vehicles=vehicles,
    )


Verdict = Literal["a_lower", "b_lower", "equal", "undetermined", "not_comparable"]


class GroupComparison(FrozenModel):
    """Demora de A frente a B en un grupo (toda la cohorte o un acceso), con la censura a la vista.

    ``difference_s`` = media de A menos media de B, solo si las dos cohortes del grupo terminaron.
    ``a`` y ``b`` son los resúmenes de cada lado, con sus inconclusos y no insertados.
    """

    verdict: Verdict
    reason: str
    difference_s: float | None
    a: DelaySummary
    b: DelaySummary


class CohortComparison(FrozenModel):
    """Comparación de la demora de dos corridas con la misma cohorte (QA26)."""

    same_cohort: bool
    total: GroupComparison
    by_access: dict[str, GroupComparison]


def _compare_group(a: DelaySummary, b: DelaySummary, tolerance_s: float) -> GroupComparison:
    def result(verdict: Verdict, reason: str, difference: float | None = None) -> GroupComparison:
        return GroupComparison(verdict=verdict, reason=reason, difference_s=difference, a=a, b=b)

    if a.requested == 0:  # misma cohorte: los dos lados tienen los mismos pedidos
        return result("not_comparable", "el grupo no tiene vehículos pedidos")
    if a.mean_delay_s is not None and b.mean_delay_s is not None:
        difference = a.mean_delay_s - b.mean_delay_s
        if abs(difference) <= tolerance_s:
            return result("equal", "las dos cohortes terminaron; medias iguales", difference)
        verdict: Verdict = "a_lower" if difference < 0 else "b_lower"
        return result(verdict, "las dos cohortes terminaron", difference)
    sides: tuple[tuple[DelaySummary, DelaySummary, Verdict], ...] = (
        (a, b, "a_lower"),
        (b, a, "b_lower"),
    )
    for complete, censored, side in sides:
        bound = censored.lower_bound_mean_delay_s
        if complete.mean_delay_s is not None and bound is not None:
            if complete.mean_delay_s < bound - tolerance_s:
                return result(
                    side,
                    "la otra cohorte está censurada, pero su cota inferior ya supera esta media",
                )
            return result(
                "undetermined",
                "una cohorte está censurada y su cota inferior no alcanza para decidir",
            )
    return result("undetermined", "las dos cohortes están censuradas: no hay medias completas")


def _cohort_key(cohort: CohortDelay) -> set[tuple[str, str, str]]:
    return {(v.vehicle_id, v.movement_id, v.vehicle_class) for v in cohort.vehicles}


def compare_cohorts(a: CohortDelay, b: CohortDelay, tolerance_s: float) -> CohortComparison:
    """Compara la demora de dos corridas (por ejemplo, dos planes) sin la media sesgada (D12).

    Solo se compara la **misma cohorte** (los mismos vehículos pedidos). Dos completas: la
    diferencia de medias, igual dentro de ``tolerance_s`` (s). Una completa y otra censurada: la
    completa es menor solo si su media queda por debajo de la cota inferior de la otra; si no,
    ``undetermined``. Dos censuradas: ``undetermined``. La media de los que terminaron nunca se usa.
    """
    same = _cohort_key(a) == _cohort_key(b)
    accesses = sorted(set(a.by_access) | set(b.by_access))
    if not same:
        reason = "no son la misma cohorte: los vehículos pedidos difieren"
        return CohortComparison(
            same_cohort=False,
            total=GroupComparison(
                verdict="not_comparable", reason=reason, difference_s=None, a=a.total, b=b.total
            ),
            by_access={},
        )
    return CohortComparison(
        same_cohort=True,
        total=_compare_group(a.total, b.total, tolerance_s),
        by_access={
            name: _compare_group(a.by_access[name], b.by_access[name], tolerance_s)
            for name in accesses
        },
    )
