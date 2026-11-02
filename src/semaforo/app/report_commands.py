"""Casos de uso de los comandos ``report case`` y ``report data`` (DEV09 F4, decisión D12).

Cada uno lee sus entradas con verificación, publica el informe y devuelve un resumen. Un caso
inválido sí genera informe (``case_status`` dice cómo quedó); un caso que no se puede leer, un
reporte de calidad alterado o de otro caso no generan nada y lanzan un error con su código de
salida.
"""

from datetime import datetime
from pathlib import Path
from typing import Literal

from semaforo.app.report_inputs import load_case_inputs, load_data_inputs
from semaforo.app.reports import INDEX_FILE, publish_case_report, publish_data_report
from semaforo.caso.case_report_models import ReportStatus
from semaforo.dominio.base_model import FrozenModel

__all__ = ["ReportResult", "report_case", "report_data"]


class ReportResult(FrozenModel):
    """Resumen de un informe publicado. Las rutas son relativas al espacio de trabajo."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["published"] = "published"
    kind: Literal["caso", "datos"]
    case_id: str | None
    case_status: ReportStatus
    folder: str
    index: str


def report_case(workspace: Path, case_path: Path, now: datetime | None = None) -> ReportResult:
    """Publica el informe del caso de ``case_path``.

    Raises:
        DomainError: CasoError si el archivo no se puede leer (PATH_NOT_ALLOWED o INPUT_SCHEMA) o
            cambió mientras se leía (HASH_MISMATCH); TrazabilidadError RUN_EXISTS si el informe ya
            existe.
    """
    inputs = load_case_inputs(case_path)
    folder = publish_case_report(workspace, inputs, now)
    return _result("caso", inputs.report.case_id, inputs.report.status, workspace, folder)


def report_data(
    workspace: Path, case_path: Path, quality_folder: Path, now: datetime | None = None
) -> ReportResult:
    """Publica el informe de los datos del reporte de calidad ``quality_folder``.

    Raises:
        DomainError: lo de ``report_case``; además, TrazabilidadError si el reporte de calidad no
            existe o no es válido (INPUT_SCHEMA), está alterado (HASH_MISMATCH), tiene enlaces
            (PATH_NOT_ALLOWED) o no es de este caso (INPUT_SCHEMA o HASH_MISMATCH).
    """
    inputs = load_data_inputs(case_path, quality_folder)
    folder = publish_data_report(workspace, inputs, now)
    report = inputs.case.report
    return _result("datos", report.case_id, report.status, workspace, folder)


def _result(
    kind: Literal["caso", "datos"],
    case_id: str | None,
    case_status: ReportStatus,
    workspace: Path,
    folder: Path,
) -> ReportResult:
    return ReportResult(
        kind=kind,
        case_id=case_id,
        case_status=case_status,
        folder=folder.relative_to(workspace).as_posix(),
        index=(folder / INDEX_FILE).relative_to(workspace).as_posix(),
    )
