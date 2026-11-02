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
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.case import Case, canonical_sha256
from semaforo.dominio.errors import ErrorCode
from semaforo.trazabilidad.fs import publish_files, read_at_most
from semaforo.trazabilidad.store import TrazabilidadError, utc_now
from semaforo.trazabilidad.verify import read_verified

__all__ = [
    "DETAIL_FILE",
    "MANIFEST_FILE",
    "MAX_FILE_BYTES",
    "SUMMARY_FILE",
    "QualityData",
    "QualityExclusion",
    "QualityGap",
    "QualityManifest",
    "QualityMissing",
    "QualityMovement",
    "QualityReport",
    "QualityRow",
    "QualitySummary",
    "QualityWindow",
    "build_report",
    "publish_quality",
    "read_quality_data",
    "read_quality_report",
]

DETAIL_FILE = "calidad.csv"
SUMMARY_FILE = "resumen.json"
MANIFEST_FILE = "manifiesto.json"
CSV_DELIMITER = ";"
DISPLAY_DECIMALS = 3
SHORT_HASH_CHARS = 8
SAFE_FOLDER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# Tope de lectura de cada archivo del reporte (DEV09 F1): una planilla de este tamaño ya tiene
# cientos de miles de filas; más que eso no es un reporte de calidad de aforos de un cruce.
MAX_FILE_BYTES = 32 * 1024 * 1024
_QUOTED_TEXT = re.compile(r'="((?:[^"]|"")*)"', re.DOTALL)
_INTEGER = re.compile(r"-?\d+")
_DECIMAL = re.compile(r"-?\d+\.\d+")
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


class QualityManifest(FrozenModel):
    """Manifiesto de un reporte de calidad publicado (``manifiesto.json``)."""

    schema_version: str
    created_at: str
    case_id: str
    case_sha256: str
    observed_sha256: str
    control_sha256: str
    max_relative_error: float | None
    files: dict[str, str]


def read_quality_report(folder: Path) -> QualityManifest:
    """Manifiesto de un reporte de calidad publicado, después de comprobar la carpeta (DEV08 F1).

    Raises:
        TrazabilidadError: PATH_NOT_ALLOWED si hay enlaces; INPUT_SCHEMA si la carpeta o el
            manifiesto no existen o no son válidos; HASH_MISMATCH si sobra, falta o cambió algo.
    """
    return read_verified(folder, MANIFEST_FILE, QualityManifest, lambda manifest: manifest.files)


class QualityWindow(FrozenModel):
    """Ventana de estudio y su cobertura (``window`` de ``resumen.json``)."""

    start: str
    end: str
    declared: bool
    window_s: float
    covered_s: float
    coverage: float
    meets_minimum: bool | None


class QualityMovement(FrozenModel):
    """Cobertura de un movimiento."""

    movement_id: str
    covered_s: float
    coverage: float
    meets_minimum: bool | None


class QualityGap(FrozenModel):
    """Un hueco de la ventana sin ninguna observación."""

    start: str
    end: str


class QualityMissing(FrozenModel):
    """Una combinación de movimiento y clase que falta en un periodo."""

    observation_id: str
    start: str
    end: str
    movement_id: str
    vehicle_class: str


class QualityExclusion(FrozenModel):
    """Una comparación excluida, con su causa. ``relative_error`` es el valor exacto."""

    observation_id: str | None
    start: str
    end: str
    movement_id: str
    vehicle_class: str
    relative_error: float
    reason: str


class QualitySummary(FrozenModel):
    """Contenido de ``resumen.json``."""

    schema_version: str
    case_id: str
    observed_sha256: str
    control_sha256: str
    window: QualityWindow
    per_movement: list[QualityMovement]
    gaps: list[QualityGap]
    overlaps: list[list[str]]
    outside_window: list[str]
    windows_by_status: dict[str, int]
    missing: list[QualityMissing]
    max_relative_error: float | None
    exclusions: list[QualityExclusion]


class QualityRow(FrozenModel):
    """Una fila de ``calidad.csv``. Los campos vacíos de la planilla son ``None``.

    Una ventana sin pareja o no comparable ocupa una sola fila sin movimiento ni clase.
    ``relative_error`` es el valor redondeado a tres decimales que muestra la planilla.
    """

    observation_id: str
    control_source_id: str
    start: str
    end: str
    movement_id: str | None
    vehicle_class: str | None
    observed: int | None
    control: int | None
    absolute_error: int | None
    relative_error: float | None
    relative_reason: str | None
    status: str
    status_reason: str | None


class QualityData(FrozenModel):
    """Un reporte de calidad publicado, leído con sus huellas comprobadas."""

    manifest: QualityManifest
    summary: QualitySummary
    rows: list[QualityRow]


def read_quality_data(folder: Path) -> QualityData:
    """Manifiesto, resumen y planilla de un reporte de calidad publicado (DEV09 F1).

    Primero se verifica la carpeta (``read_quality_report``). Después, los bytes que se interpretan
    se leen una sola vez y se comparan con la huella del manifiesto, para que un archivo cambiado
    entre la verificación y la lectura no se use.

    Raises:
        TrazabilidadError: PATH_NOT_ALLOWED si hay enlaces; INPUT_SCHEMA si algo no existe, es
            demasiado grande o no tiene el formato que escribe ``publish_quality``; HASH_MISMATCH
            si sobra, falta o cambió algo.
    """
    manifest = read_quality_report(folder)
    detail = _read_member(folder, manifest, DETAIL_FILE)
    summary_bytes = _read_member(folder, manifest, SUMMARY_FILE)
    try:
        summary = QualitySummary.model_validate_json(summary_bytes)
    except ValueError as error:
        raise _unreadable(SUMMARY_FILE, "no tiene el formato de un resumen de calidad") from error
    _same_report(manifest, summary)
    return QualityData(manifest=manifest, summary=summary, rows=_detail_rows(detail))


def _unreadable(name: str, reason: str) -> TrazabilidadError:
    return TrazabilidadError(ErrorCode.INPUT_SCHEMA, f"{name}: {reason}", name)


def _read_member(folder: Path, manifest: QualityManifest, name: str) -> bytes:
    expected = manifest.files.get(name)
    if expected is None:
        raise _unreadable(name, "el manifiesto no lo incluye")
    try:
        with (folder / name).open("rb") as stream:
            data = read_at_most(stream, MAX_FILE_BYTES + 1)
    except OSError as error:
        raise _unreadable(name, f"no se puede leer ({type(error).__name__})") from error
    if len(data) > MAX_FILE_BYTES:
        raise _unreadable(name, "es demasiado grande")
    if hashlib.sha256(data).hexdigest() != expected:
        raise TrazabilidadError(ErrorCode.HASH_MISMATCH, "un archivo fue modificado", name)
    return data


def _same_report(manifest: QualityManifest, summary: QualitySummary) -> None:
    """El resumen y el manifiesto hablan del mismo caso, los mismos archivos y el mismo límite."""
    pairs = {
        "case_id": (manifest.case_id, summary.case_id),
        "observed_sha256": (manifest.observed_sha256, summary.observed_sha256),
        "control_sha256": (manifest.control_sha256, summary.control_sha256),
        "max_relative_error": (manifest.max_relative_error, summary.max_relative_error),
    }
    for field, (from_manifest, from_summary) in pairs.items():
        if from_manifest != from_summary:
            raise _unreadable(SUMMARY_FILE, f"{field} no coincide con el manifiesto")


def _detail_rows(data: bytes) -> list[QualityRow]:
    try:
        text = data.decode("utf-8-sig")
        records = list(csv.reader(io.StringIO(text, newline=""), delimiter=CSV_DELIMITER))
    except (UnicodeDecodeError, csv.Error) as error:
        raise _unreadable(DETAIL_FILE, "no es una planilla de texto válida") from error
    if not records or records[0] != DETAIL_HEADER:
        raise _unreadable(DETAIL_FILE, "el encabezado no es el de la planilla de calidad")
    return [_row(number, record) for number, record in enumerate(records[1:], start=2)]


def _row(number: int, record: list[str]) -> QualityRow:
    if len(record) != len(DETAIL_HEADER):
        raise _unreadable(DETAIL_FILE, f"la línea {number} no tiene {len(DETAIL_HEADER)} columnas")
    status = record[11]
    if status not in set(STATUS_LABELS.values()):
        raise _unreadable(DETAIL_FILE, f"la línea {number} tiene un estado desconocido")
    for instant in (record[2], record[3]):
        try:
            datetime.fromisoformat(instant)
        except ValueError:
            raise _unreadable(DETAIL_FILE, f"la línea {number} tiene una fecha inválida") from None
    return QualityRow(
        observation_id=_untext(number, record[0]),
        control_source_id=_untext(number, record[1]),
        start=record[2],
        end=record[3],
        movement_id=_optional_text(number, record[4]),
        vehicle_class=_optional_text(number, record[5]),
        observed=_optional_integer(number, record[6]),
        control=_optional_integer(number, record[7]),
        absolute_error=_optional_integer(number, record[8]),
        relative_error=_optional_decimal(number, record[9]),
        relative_reason=record[10] or None,
        status=status,
        status_reason=record[12] or None,
    )


def _untext(number: int, field: str) -> str:
    """Inversa de ``_text``: el identificador que iba entre ``="..."``."""
    match = _QUOTED_TEXT.fullmatch(field)
    if match is None:
        raise _unreadable(DETAIL_FILE, f"la línea {number} tiene un identificador mal formado")
    return match.group(1).replace('""', '"')


def _optional_text(number: int, field: str) -> str | None:
    return None if field == "" else _untext(number, field)


def _optional_integer(number: int, field: str) -> int | None:
    if field == "":
        return None
    if _INTEGER.fullmatch(field) is None:
        raise _unreadable(DETAIL_FILE, f"la línea {number} tiene un conteo que no es entero")
    return int(field)


def _optional_decimal(number: int, field: str) -> float | None:
    if field == "":
        return None
    if _DECIMAL.fullmatch(field) is None:
        raise _unreadable(DETAIL_FILE, f"la línea {number} tiene un error relativo mal escrito")
    return float(field)


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
