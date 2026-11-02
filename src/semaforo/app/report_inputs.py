"""Entradas de las vistas de Caso y de Datos (DEV09 F1, decisiones D4 y D5).

- **Caso:** el archivo ``case.json`` se lee dos veces, una para el reporte de las reglas
  (``validate_case``) y otra para el caso mismo (``read_case``). Si las dos lecturas no describen el
  mismo caso, el archivo cambió a medias y no se muestra nada.
- **Datos:** el reporte de calidad de DEV05 se lee verificado (``read_quality_data``) y se
  comprueba que sea del caso dado, por su huella. Si no, no se muestra nada.

Un caso inválido sí se muestra: el informe existe para ver sus problemas.
"""

from dataclasses import dataclass
from pathlib import Path

from semaforo.caso.case_report_models import CaseReport
from semaforo.caso.case_validation import read_case, validate_case
from semaforo.caso.errors import CasoError
from semaforo.datos.quality_report import QualityData, read_quality_data
from semaforo.dominio.case import Case, CaseInvalidError, canonical_sha256
from semaforo.dominio.errors import ErrorCode
from semaforo.trazabilidad.store import TrazabilidadError

__all__ = ["CaseInputs", "DataInputs", "load_case_inputs", "load_data_inputs"]

PATH_EXIT = 5


@dataclass(frozen=True)
class CaseInputs:
    """El reporte de las reglas y, si el caso es válido, el caso.

    ``case`` es ``None`` si el archivo no cumple el contrato o es incoherente: el reporte dice
    por qué.
    """

    report: CaseReport
    case: Case | None


@dataclass(frozen=True)
class DataInputs:
    """El caso y su reporte de calidad, ya vinculados."""

    case: CaseInputs
    quality: QualityData


def load_case_inputs(path: Path) -> CaseInputs:
    """Reporte de las reglas y caso de ``path``.

    Raises:
        CasoError: PATH_NOT_ALLOWED si la ruta es un enlace o una unión; INPUT_SCHEMA si no existe
            o no se puede leer; HASH_MISMATCH si el archivo cambió entre las dos lecturas.
    """
    case = _read_valid_case(path)
    report = validate_case(path)
    if report.error is not None:
        code = (
            ErrorCode.PATH_NOT_ALLOWED if report.exit_code == PATH_EXIT else ErrorCode.INPUT_SCHEMA
        )
        raise CasoError(code, report.error)
    if not _same_case(case, report):
        raise CasoError(ErrorCode.HASH_MISMATCH, "el archivo del caso cambió mientras se leía")
    return CaseInputs(report=report, case=case)


def _read_valid_case(path: Path) -> Case | None:
    try:
        return read_case(path)
    except CaseInvalidError:
        return None


def _same_case(case: Case | None, report: CaseReport) -> bool:
    """Las dos lecturas describen lo mismo: el mismo caso válido, o un caso inválido en ambas."""
    if case is None:
        return report.status == "invalid"
    return report.case_sha256 == canonical_sha256(case)


def load_data_inputs(case_path: Path, quality_folder: Path) -> DataInputs:
    """El caso y su reporte de calidad, comprobando que el reporte sea de ese caso.

    Raises:
        CasoError: lo de ``load_case_inputs``; INPUT_SCHEMA si el archivo del caso no llega a
            tener estructura válida (sin su huella no se puede vincular el reporte).
        TrazabilidadError: lo de ``read_quality_data``; INPUT_SCHEMA si el reporte es de otro
            caso; HASH_MISMATCH si el caso cambió desde que se generó el reporte.
    """
    inputs = load_case_inputs(case_path)
    digest = inputs.report.case_sha256
    if digest is None:
        raise CasoError(
            ErrorCode.INPUT_SCHEMA,
            "el caso no tiene una estructura válida; sin su huella no se puede comprobar que el "
            "reporte de calidad sea de este caso",
        )
    quality = read_quality_data(quality_folder)
    if quality.manifest.case_id != inputs.report.case_id:
        raise TrazabilidadError(
            ErrorCode.INPUT_SCHEMA, "el reporte de calidad es de otro caso", "case_id"
        )
    if quality.manifest.case_sha256 != digest:
        raise TrazabilidadError(
            ErrorCode.HASH_MISMATCH,
            "el caso cambió desde que se generó el reporte de calidad",
            "case_sha256",
        )
    return DataInputs(case=inputs, quality=quality)
