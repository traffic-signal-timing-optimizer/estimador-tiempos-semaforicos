"""Reglas de un reintento: ``retry_of`` apunta a una corrida que de verdad se puede reintentar (D9).

Reintentar siempre es una corrida nueva, con su ``run_id`` nuevo; la anterior no se toca ni se
sobrescribe. Se puede reintentar una corrida ``failed``, ``cancelled`` o interrumpida del mismo
caso, la misma versión del caso y el mismo escenario. Una exitosa no se reintenta.
"""

from pathlib import Path

from semaforo.dominio.errors import ErrorCode
from semaforo.trazabilidad.interrupted import list_interrupted
from semaforo.trazabilidad.manifest import check_run_id
from semaforo.trazabilidad.store import MANIFEST, RunSpec, TrazabilidadError, read_run

__all__ = ["check_retry"]


def _refused(message: str) -> TrazabilidadError:
    return TrazabilidadError(ErrorCode.INPUT_SCHEMA, message, "retry_of")


def _same(
    spec: RunSpec, case_id: str | None, case_version: str | None, scenario: str | None
) -> str | None:
    """Qué difiere entre el reintento y la corrida anterior; ``None`` si es lo mismo."""
    for label, wanted, found in (
        ("el caso", spec.case_id, case_id),
        ("la versión del caso", spec.case_version, case_version),
        ("el escenario", spec.scenario_id, scenario),
    ):
        if wanted != found:
            return label
    return None


def check_retry(root: Path, spec: RunSpec) -> None:
    """Comprueba ``spec.retry_of`` contra las corridas de ``root``. Sin ``retry_of`` no hace nada.

    Raises:
        TrazabilidadError: PATH_NOT_ALLOWED si el identificador no es un nombre de carpeta seguro;
            INPUT_SCHEMA si la corrida no existe, es exitosa, o es de otro caso, versión o
            escenario; HASH_MISMATCH si la corrida publicada fue alterada.
    """
    if spec.retry_of is None:
        return
    try:
        run_id = check_run_id(spec.retry_of)
    except ValueError as error:
        raise TrazabilidadError(ErrorCode.PATH_NOT_ALLOWED, str(error), "retry_of") from error
    if (root / run_id / MANIFEST).is_file():
        previous = read_run(root, run_id)
        if previous.status == "succeeded":
            raise _refused("una corrida exitosa no se reintenta")
        different = _same(spec, previous.case_id, previous.case_version, previous.scenario_id)
    else:
        interrupted = [item for item in list_interrupted(root) if item.run_id == run_id]
        if not interrupted:
            raise _refused("la corrida a reintentar no existe")
        different = _same(
            spec, interrupted[0].case_id, interrupted[0].case_version, interrupted[0].scenario_id
        )
    if different is not None:
        raise _refused(f"{different} no coincide con el de la corrida a reintentar")
