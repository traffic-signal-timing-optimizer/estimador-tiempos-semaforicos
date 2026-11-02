"""Publicación de los informes HTML del caso y de los datos (DEV09 F2, decisión D11).

Cada informe se publica como una carpeta nueva, que nunca se sobrescribe:

``<espacio de trabajo>/reportes/informes/<tipo>/<id-del-caso>/<AAAAMMDDTHHMMSSZ>_<huella-corta>/``

con ``index.html`` y ``manifiesto.json``. El manifiesto guarda la huella de cada archivo y las
huellas de lo que se usó para generarlo, de modo que el informe remite a sus datos concretos.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from semaforo.app.report_case_view import render_case
from semaforo.app.report_data_view import render_data
from semaforo.app.report_inputs import CaseInputs, DataInputs
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.errors import ErrorCode
from semaforo.trazabilidad.fs import publish_files
from semaforo.trazabilidad.store import TrazabilidadError, utc_now
from semaforo.trazabilidad.verify import read_verified

__all__ = [
    "INDEX_FILE",
    "MANIFEST_FILE",
    "REPORTS",
    "ReportManifest",
    "publish_case_report",
    "publish_data_report",
    "read_report",
]

REPORTS = "reportes/informes"
INDEX_FILE = "index.html"
MANIFEST_FILE = "manifiesto.json"
UNIDENTIFIED = "sin-identificar"
SHORT_HASH_CHARS = 8
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass(frozen=True)
class _Report:
    """Lo que se publica: el tipo, el caso, el HTML y las huellas de lo que se usó."""

    kind: Literal["caso", "datos"]
    case_id: str | None
    html: bytes
    inputs: dict[str, str]


class ReportManifest(FrozenModel):
    """Manifiesto de un informe publicado (``manifiesto.json``)."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    kind: Literal["caso", "datos"]
    created_at: str
    case_id: str | None
    inputs: dict[str, str]
    files: dict[str, str]


def publish_case_report(workspace: Path, inputs: CaseInputs, now: datetime | None = None) -> Path:
    """Publica el informe del caso y devuelve su carpeta.

    Raises:
        TrazabilidadError: RUN_EXISTS si la carpeta de destino ya existe (no se sobrescribe).
    """
    moment = utc_now() if now is None else now
    html = render_case(inputs, moment).encode("utf-8")
    case_inputs: dict[str, str] = {}
    if inputs.report.case_sha256 is not None:
        case_inputs["case_sha256"] = inputs.report.case_sha256
    report = _Report("caso", inputs.report.case_id, html, case_inputs)
    return _publish(workspace, report, moment)


def publish_data_report(workspace: Path, inputs: DataInputs, now: datetime | None = None) -> Path:
    """Publica el informe de los datos y devuelve su carpeta.

    El manifiesto guarda las huellas del caso, de los dos conteos y de cada archivo del reporte de
    calidad del que salieron los números.

    Raises:
        TrazabilidadError: RUN_EXISTS si la carpeta de destino ya existe (no se sobrescribe).
    """
    moment = utc_now() if now is None else now
    html = render_data(inputs, moment).encode("utf-8")
    quality = inputs.quality.manifest
    used = {
        "case_sha256": quality.case_sha256,
        "observed_sha256": quality.observed_sha256,
        "control_sha256": quality.control_sha256,
    }
    for name, digest in sorted(quality.files.items()):
        used[f"calidad/{name}"] = digest
    report = _Report("datos", inputs.case.report.case_id, html, used)
    return _publish(workspace, report, moment)


def read_report(folder: Path) -> ReportManifest:
    """Manifiesto de un informe publicado, después de comprobar la carpeta.

    Raises:
        TrazabilidadError: PATH_NOT_ALLOWED si hay enlaces; INPUT_SCHEMA si la carpeta o el
            manifiesto no existen o no son válidos; HASH_MISMATCH si sobra, falta o cambió algo.
    """
    return read_verified(folder, MANIFEST_FILE, ReportManifest, lambda manifest: manifest.files)


def _publish(workspace: Path, report: _Report, moment: datetime) -> Path:
    digest = hashlib.sha256(report.html).hexdigest()
    manifest = ReportManifest(
        kind=report.kind,
        created_at=moment.astimezone(UTC).isoformat(),
        case_id=report.case_id,
        inputs=report.inputs,
        files={INDEX_FILE: digest},
    )
    case_id = report.case_id
    name = case_id if case_id is not None and _SAFE_NAME.fullmatch(case_id) else UNIDENTIFIED
    stamp = f"{moment.astimezone(UTC):%Y%m%dT%H%M%SZ}_{digest[:SHORT_HASH_CHARS]}"
    final = workspace / REPORTS / report.kind / name / stamp
    body = (json.dumps(manifest.model_dump(), indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        publish_files(final, {INDEX_FILE: report.html, MANIFEST_FILE: body})
    except FileExistsError as error:
        raise TrazabilidadError(
            ErrorCode.RUN_EXISTS,
            "ya existe un informe con ese nombre o se publica otro igual: repita el comando",
            final.name,
        ) from error
    return final
