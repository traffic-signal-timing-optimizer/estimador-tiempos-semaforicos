"""Reporte de calidad de aforos: planilla de detalle, resumen y manifiesto (DEV05 F3, HU03).

Decisiones D6 y D7 de ``2026-10-30-dev05-f0-decisiones.md``:

- **Planilla** ``calidad.csv``: una fila por ventana, movimiento y clase. Las ventanas que no se
  pueden comparar o no tienen pareja ocupan una sola fila con su estado y su motivo. Separador
  ``;``, UTF-8 con BOM y fin de línea de Windows, como las planillas de QA23 y QA24. Los
  identificadores van entre ``="..."`` para que Excel no los convierta en números.
- **Resumen** ``resumen.json``: cobertura, huecos, solapes, faltantes, exclusiones con su motivo y
  el límite usado. Los valores son exactos.
- **Redondeo (D7):** la planilla muestra el error relativo con tres decimales; el resumen y el
  manifiesto guardan el valor exacto.
- **Manifiesto** ``manifiesto.json``: huellas SHA-256 de los dos archivos de entrada, del caso y de
  cada archivo del reporte.

Se publica en ``datos/derivados/calidad/<id-del-caso>/<AAAAMMDDTHHMMSSZ>_<huella-corta>/``. Una
carpeta publicada nunca se sobrescribe.
"""

import csv
import hashlib
import io
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from semaforo.datos.coverage import Coverage, MissingEntry
from semaforo.datos.quality import Exclusion, QualityComparison, QualityError, WindowComparison
from semaforo.dominio.case import Case, canonical_sha256
from semaforo.trazabilidad.fs import publish_files
from semaforo.trazabilidad.store import utc_now

__all__ = [
    "DETAIL_FILE",
    "MANIFEST_FILE",
    "SUMMARY_FILE",
    "QualityReport",
    "build_report",
    "publish_quality",
]

DETAIL_FILE = "calidad.csv"
SUMMARY_FILE = "resumen.json"
MANIFEST_FILE = "manifiesto.json"
CSV_DELIMITER = ";"
DISPLAY_DECIMALS = 3
SHORT_HASH_CHARS = 8
SAFE_FOLDER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
DETAIL_HEADER = [
    "observation_id",
    "control_source_id",
    "start",
    "end",
    "movement_id",
    "vehicle_class",
    "observado",
    "control",
    "error_absoluto",
    "error_relativo",
    "motivo_error_relativo",
    "estado",
    "motivo_estado",
]
STATUS_LABELS = {
    "comparable": "comparable",
    "only_observed": "sin pareja",
    "only_control": "sin pareja",
    "not_comparable": "no comparable",
    "excluded": "excluido",
}


@dataclass(frozen=True)
class QualityReport:
    """Los tres archivos del reporte, listos para publicar."""

    files: dict[str, bytes]
    folder_key: str


@dataclass(frozen=True)
class ReportInputs:
    """Todo lo que el reporte necesita, ya calculado por F1 y F2."""

    comparison: QualityComparison
    coverage: Coverage
    exclusions: tuple[Exclusion, ...]
    missing: tuple[MissingEntry, ...]
    case: Case
    max_relative_error: float | None


def build_report(inputs: ReportInputs, created_at: datetime) -> QualityReport:
    """Archivos del reporte, sin escribirlos. Función pura."""
    comparison, coverage, case = inputs.comparison, inputs.coverage, inputs.case
    exclusions, missing = inputs.exclusions, inputs.missing
    max_relative_error = inputs.max_relative_error
    if SAFE_FOLDER_NAME.fullmatch(case.case_id) is None:
        raise QualityError(
            "el ID del caso solo puede llevar letras, números, punto, guion y guion bajo para "
            "usarse como nombre de carpeta",
            "case_id",
        )
    detail = _detail_csv(comparison, exclusions)
    summary = _summary_json(comparison, coverage, exclusions, missing, max_relative_error)
    files = {DETAIL_FILE: detail, SUMMARY_FILE: summary}
    manifest = _manifest_json(comparison, case, files, max_relative_error, created_at)
    files[MANIFEST_FILE] = manifest
    stamp = created_at.astimezone(UTC)
    folder = f"{stamp:%Y%m%dT%H%M%SZ}_{hashlib.sha256(detail).hexdigest()[:SHORT_HASH_CHARS]}"
    return QualityReport(files=files, folder_key=folder)


def publish_quality(root: Path, inputs: ReportInputs, now: datetime | None = None) -> Path:
    """Publica el reporte en ``root/<id-del-caso>/<fecha>_<huella>/`` y devuelve esa carpeta.

    Raises:
        QualityError: si el ID del caso no sirve como nombre de carpeta.
        FileExistsError: si la carpeta ya existe (nunca se sobrescribe).
    """
    moment = utc_now() if now is None else now
    report = build_report(inputs, moment)
    final = root / inputs.case.case_id / report.folder_key
    publish_files(final, report.files)
    return final


def _text(value: str) -> str:
    """Identificador para Excel: entre ``="..."`` para que no se convierta en número."""
    return '="' + value.replace('"', '""') + '"'


def _display(value: float | None) -> str:
    return "" if value is None else f"{value:.{DISPLAY_DECIMALS}f}"


def _detail_csv(comparison: QualityComparison, exclusions: Sequence[Exclusion]) -> bytes:
    excluded = {(e.start, e.end, e.movement_id, e.vehicle_class): e.reason for e in exclusions}
    rows: list[list[str]] = [DETAIL_HEADER]
    for window in comparison.windows:
        if window.status == "comparable":
            rows.extend(_comparable_rows(window, excluded))
        else:
            rows.append(_unpaired_row(window))
    return _encode(rows)


def _comparable_rows(
    window: WindowComparison, excluded: dict[tuple[datetime, datetime, str, str], str]
) -> list[list[str]]:
    rows: list[list[str]] = []
    for count in window.counts:
        reason = excluded.get((window.start, window.end, count.movement_id, count.vehicle_class))
        rows.append(
            [
                _text(window.observed_id or ""),
                _text(window.control_source_id or ""),
                window.start.isoformat(),
                window.end.isoformat(),
                _text(count.movement_id),
                _text(count.vehicle_class),
                str(count.observed),
                str(count.control),
                str(count.absolute_error),
                _display(count.relative_error),
                count.relative_reason or "",
                STATUS_LABELS["excluded" if reason else "comparable"],
                reason or "",
            ]
        )
    return rows


def _unpaired_row(window: WindowComparison) -> list[str]:
    estado = STATUS_LABELS[window.status]
    if window.status == "only_observed":
        motivo = "la ventana solo existe en el conteo principal"
    elif window.status == "only_control":
        motivo = "la ventana solo existe en el conteo de control"
    else:
        motivo = window.reason or ""
    return [
        _text(window.observed_id or ""),
        _text(window.control_source_id or ""),
        window.start.isoformat(),
        window.end.isoformat(),
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        estado,
        motivo,
    ]


def _encode(rows: list[list[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=CSV_DELIMITER, lineterminator="\r\n")
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def _summary_json(
    comparison: QualityComparison,
    coverage: Coverage,
    exclusions: Sequence[Exclusion],
    missing: Sequence[MissingEntry],
    max_relative_error: float | None,
) -> bytes:
    statuses = {status: 0 for status in STATUS_LABELS if status != "excluded"}
    for window in comparison.windows:
        statuses[window.status] += 1
    data = {
        "schema_version": "1.0.0",
        "case_id": comparison.case_id,
        "observed_sha256": comparison.observed_sha256,
        "control_sha256": comparison.control_sha256,
        "window": {
            "start": coverage.window_start.isoformat(),
            "end": coverage.window_end.isoformat(),
            "declared": coverage.window_declared,
            "window_s": coverage.window_s,
            "covered_s": coverage.covered_s,
            "coverage": coverage.coverage,
            "meets_minimum": coverage.meets_minimum,
        },
        "per_movement": [
            {
                "movement_id": m.movement_id,
                "covered_s": m.covered_s,
                "coverage": m.coverage,
                "meets_minimum": m.meets_minimum,
            }
            for m in coverage.per_movement
        ],
        "gaps": [{"start": g.start.isoformat(), "end": g.end.isoformat()} for g in coverage.gaps],
        "overlaps": [list(pair) for pair in coverage.overlaps],
        "outside_window": list(coverage.outside_window),
        "windows_by_status": statuses,
        "missing": [
            {
                "observation_id": e.observation_id,
                "start": e.start.isoformat(),
                "end": e.end.isoformat(),
                "movement_id": e.movement_id,
                "vehicle_class": e.vehicle_class,
            }
            for e in missing
        ],
        "max_relative_error": max_relative_error,
        "exclusions": [
            {
                "observation_id": e.observed_id,
                "start": e.start.isoformat(),
                "end": e.end.isoformat(),
                "movement_id": e.movement_id,
                "vehicle_class": e.vehicle_class,
                "relative_error": e.relative_error,
                "reason": e.reason,
            }
            for e in exclusions
        ],
    }
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _manifest_json(
    comparison: QualityComparison,
    case: Case,
    files: dict[str, bytes],
    max_relative_error: float | None,
    created_at: datetime,
) -> bytes:
    data = {
        "schema_version": "1.0.0",
        "created_at": created_at.astimezone(UTC).isoformat(),
        "case_id": comparison.case_id,
        "case_sha256": canonical_sha256(case),
        "observed_sha256": comparison.observed_sha256,
        "control_sha256": comparison.control_sha256,
        "max_relative_error": max_relative_error,
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
    }
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
