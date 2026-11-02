"""MAE del ciclo y de cada verde entre planes estimados y de referencia (DEV19 F4; D13; I5).

I5 del plan de pruebas: «MAE del ciclo y cada verde, segundos; comparar con mediana; reportar
denominadores y faltantes». Cada plan se reconstruye con DEV13 (``reconstruct``), así que el ciclo
cuenta cada slot una vez y el verde de un grupo es el de sus slots, sin doble conteo de solapes.

Un par sin plan estimado (la consulta lo rechazó o falló) o sin plan de referencia (la búsqueda
no encontró uno, ``no_reference``) **no se descarta en silencio**: se cuenta como faltante y el
MAE se calcula sobre los evaluados. Para comparar con la mediana se calcula el MAE de cada
estimador con los mismos pares.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import Field

from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.case import Case
from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.timing import TimingInputError, reconstruct
from semaforo.evaluacion.errors import EvaluacionError

__all__ = ["PlanErrorSummary", "PlanPair", "plan_mae"]


@dataclass(frozen=True)
class PlanPair:
    """Un escenario: el plan estimado y el de referencia (duración de cada slot, en s), o None."""

    scenario_id: str
    predicted: Mapping[str, float] | None
    reference: Mapping[str, float] | None


class PlanErrorSummary(FrozenModel):
    """MAE (s) del ciclo y del verde de cada grupo, con sus denominadores.

    ``pairs`` = ``evaluated`` + ``missing_prediction`` + ``missing_reference``. Un par sin
    referencia cuenta como ``missing_reference`` aunque tampoco tenga predicción. Sin pares
    evaluados, los MAE son None.
    """

    pairs: int = Field(ge=0)
    evaluated: int = Field(ge=0)
    missing_prediction: int = Field(ge=0)
    missing_reference: int = Field(ge=0)
    cycle_mae_s: float | None
    green_mae_s: dict[str, float | None]


def _timing(
    case: Case, durations: Mapping[str, float], where: str
) -> tuple[float, dict[str, float]]:
    try:
        timing = reconstruct(case, durations)
    except TimingInputError as error:
        raise EvaluacionError(
            ErrorCode.INPUT_SCHEMA, f"{where} no es un plan del caso: {error.message}", where
        ) from error
    return timing.cycle_s, timing.greens_s


def plan_mae(case: Case, pairs: Sequence[PlanPair]) -> PlanErrorSummary:
    """MAE del ciclo y de cada verde sobre los pares con los dos planes.

    Raises:
        EvaluacionError: INPUT_SCHEMA si un plan no es un plan del caso (le faltan o sobran slots,
            o un valor no es un número finito no negativo).
    """
    cycle_errors: list[float] = []
    green_errors: dict[str, list[float]] = {group.id: [] for group in case.green_groups}
    missing_prediction = missing_reference = 0
    for index, pair in enumerate(pairs):
        if pair.reference is None:
            missing_reference += 1
            continue
        if pair.predicted is None:
            missing_prediction += 1
            continue
        cycle_p, greens_p = _timing(case, pair.predicted, f"pairs[{index}].predicted")
        cycle_r, greens_r = _timing(case, pair.reference, f"pairs[{index}].reference")
        cycle_errors.append(abs(cycle_p - cycle_r))
        for group_id, errors in green_errors.items():
            errors.append(abs(greens_p[group_id] - greens_r[group_id]))
    evaluated = len(cycle_errors)

    def mae(errors: list[float]) -> float | None:
        return math.fsum(errors) / evaluated if evaluated else None

    return PlanErrorSummary(
        pairs=len(pairs),
        evaluated=evaluated,
        missing_prediction=missing_prediction,
        missing_reference=missing_reference,
        cycle_mae_s=mae(cycle_errors),
        green_mae_s={group_id: mae(errors) for group_id, errors in green_errors.items()},
    )
