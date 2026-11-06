"""Un plan de tiempos como filas de ``simulacion.planes`` y ``plan_tramos`` (DEV31 F3)."""

from collections.abc import Mapping

from semaforo.bd.carga.modelo import CargaError, FileRecord, Unit
from semaforo.dominio.case import Case
from semaforo.dominio.errors import ErrorCode
from semaforo.simulacion.prepare import canonical_json_sha256

__all__ = ["CYCLE_TOLERANCE_S", "add_plan", "plan_id"]

CYCLE_TOLERANCE_S = 1e-6


def _vector(case: Case, durations: Mapping[str, float]) -> list[float]:
    order = [slot.id for slot in case.slots]
    if set(durations) != set(order):
        raise CargaError(
            ErrorCode.INPUT_SCHEMA,
            "el plan no tiene exactamente los tramos del caso",
            "durations_s",
        )
    return [float(durations[slot]) for slot in order]


def plan_id(case: Case, durations: Mapping[str, float]) -> str:
    """Huella del vector de duraciones en el orden de los tramos del caso (y del caso mismo)."""
    return canonical_json_sha256(
        {
            "caso_id": case.case_id,
            "caso_version": case.case_version,
            "duraciones_s": _vector(case, durations),
        }
    )


def add_plan(
    unit: Unit,
    case: Case,
    durations: Mapping[str, float],
    source: FileRecord,
    *,
    cycle_s: float | None = None,
) -> str:
    """Agrega el plan a ``unit`` y devuelve su ``plan_id``.

    Raises:
        CargaError: INPUT_SCHEMA si el plan no tiene los tramos del caso o su ciclo declarado no
            es la suma de sus tramos.
    """
    vector = _vector(case, durations)
    total = sum(vector)
    if cycle_s is not None and abs(cycle_s - total) > CYCLE_TOLERANCE_S:
        raise CargaError(
            ErrorCode.INPUT_SCHEMA, "el ciclo no es la suma de los tramos del plan", "cycle_s"
        )
    identifier = plan_id(case, durations)
    order = [slot.id for slot in case.slots]
    unit.add(
        "simulacion.planes",
        {
            "plan_id": identifier,
            "caso_id": case.case_id,
            "caso_version": case.case_version,
            "duraciones_s": dict(zip(order, vector, strict=True)),
            "ciclo_s": total,
        },
        source,
    )
    for slot, duration in zip(order, vector, strict=True):
        unit.add(
            "simulacion.plan_tramos",
            {
                "plan_id": identifier,
                "caso_id": case.case_id,
                "caso_version": case.case_version,
                "tramo_id": slot,
                "duracion_s": duration,
            },
            source,
        )
    return identifier
