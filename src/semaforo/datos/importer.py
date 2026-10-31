"""Importación de aforos CSV (DEV04, HU02): valida el archivo y nunca acepta una parte de él.

El archivo se lee sin modificarlo y se calcula su huella SHA-256 (original conservado). Cada fila
se valida contra el caso: encabezado exacto, campos completos, fechas con zona, conteos enteros no
negativos, claves únicas y movimientos y clases que existen en el caso. Si una sola fila falla, se
rechaza el archivo entero y el error lista todas las filas con problemas, cada una con su número de
línea, su campo y su motivo. Así ningún periodo llega a la normalización a medias.

Formato (``01_Diseno_tecnico.md``, «Aforos y calidad»): encabezado exacto de diez columnas; fechas
ISO 8601 con zona; ``end`` posterior a ``start``; la clave lógica es ``observation_id``,
``movement_id`` y ``vehicle_class``. Un ``observation_id`` identifica un periodo, así que todas
sus filas comparten inicio y fin.
"""

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from semaforo.dominio.case import Case
from semaforo.dominio.errors import DomainError, ErrorCode

__all__ = [
    "HEADER",
    "MAX_COUNTS_BYTES",
    "QUALITY_STATES",
    "CountImportError",
    "CountIssue",
    "CountRow",
    "CountsFile",
    "read_counts",
]

HEADER = (
    "case_id",
    "observation_id",
    "source_id",
    "origin",
    "start",
    "end",
    "movement_id",
    "vehicle_class",
    "count",
    "quality_state",
)
# Solo «observed» se admite hoy: la documentación no fija otros valores (pendiente del PO).
QUALITY_STATES = frozenset({"observed"})
MAX_COUNTS_BYTES = 16 * 1024 * 1024
INTEGER = re.compile(r"[0-9]+")
ENCODING = "utf-8-sig"


@dataclass(frozen=True)
class CountIssue:
    """Un problema del archivo: la línea (None si es del archivo entero), el campo y el motivo."""

    line: int | None
    field: str | None
    message: str


class CountImportError(DomainError):
    """El archivo de aforos no se acepta. Lleva todos sus problemas, el primero en el mensaje."""

    def __init__(self, issues: list[CountIssue]) -> None:
        if not issues:
            raise ValueError("un archivo rechazado tiene al menos un problema")
        first = issues[0]
        where = "" if first.line is None else f" (línea {first.line})"
        extra = f" (y {len(issues) - 1} más)" if len(issues) > 1 else ""
        super().__init__(
            ErrorCode.INPUT_SCHEMA,
            f"el archivo de aforos no es válido{where}: {first.message}{extra}",
            first.field,
        )
        self.issues = tuple(issues)


@dataclass(frozen=True)
class CountRow:
    """Una fila validada del archivo, con sus tipos ya convertidos."""

    line: int
    observation_id: str
    source_id: str
    start: datetime
    end: datetime
    movement_id: str
    vehicle_class: str
    count: int


@dataclass(frozen=True)
class CountsFile:
    """Contenido validado del archivo y la huella del original, tal como se leyó."""

    sha256: str
    size_bytes: int
    case_id: str
    rows: tuple[CountRow, ...]


def read_counts(path: Path, case: Case, max_bytes: int = MAX_COUNTS_BYTES) -> CountsFile:
    """Lee y valida ``path`` frente a ``case``. No modifica el archivo.

    Raises:
        CountImportError: si el archivo no se puede leer, supera el tamaño máximo, tiene un
            encabezado distinto o alguna fila no cumple las reglas. Lleva todos los problemas.
    """
    data = _read_bytes(path, max_bytes)
    text = _decode(data)
    records = list(csv.reader(io.StringIO(text, newline="")))
    if not records or tuple(records[0]) != HEADER:
        found = records[0] if records else []
        raise CountImportError(
            [
                CountIssue(
                    1,
                    None,
                    "el encabezado no coincide con el esperado; faltan "
                    f"{_missing(found)} y sobran {_extra(found)}",
                )
            ]
        )
    issues: list[CountIssue] = []
    rows: list[CountRow] = []
    windows: dict[str, tuple[datetime, datetime]] = {}
    keys: dict[tuple[str, str, str], int] = {}
    for number, record in enumerate(records[1:], start=2):
        if not record:
            continue
        row = _row(number, record, case, issues)
        if row is None:
            continue
        window = windows.setdefault(row.observation_id, (row.start, row.end))
        if window != (row.start, row.end):
            issues.append(
                CountIssue(
                    number,
                    "start",
                    f"el periodo {row.observation_id!r} tiene otro inicio o fin que en su "
                    "primera fila",
                )
            )
            continue
        key = (row.observation_id, row.movement_id, row.vehicle_class)
        if key in keys:
            issues.append(
                CountIssue(
                    number,
                    "observation_id",
                    f"la clave {key} ya aparece en la línea {keys[key]}; un duplicado no se "
                    "suma en silencio",
                )
            )
            continue
        keys[key] = number
        rows.append(row)
    if issues:
        raise CountImportError(issues)
    return CountsFile(
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        case_id=case.case_id,
        rows=tuple(rows),
    )


def _read_bytes(path: Path, max_bytes: int) -> bytes:
    try:
        with path.open("rb") as handle:
            data = handle.read(max_bytes + 1)
    except OSError as error:
        raise CountImportError(
            [CountIssue(None, None, f"no se puede leer el archivo ({type(error).__name__})")]
        ) from error
    if len(data) > max_bytes:
        raise CountImportError(
            [CountIssue(None, None, f"el archivo supera el límite de {max_bytes} bytes")]
        )
    return data


def _decode(data: bytes) -> str:
    try:
        return data.decode(ENCODING)
    except UnicodeDecodeError as error:
        raise CountImportError([CountIssue(None, None, "el archivo no está en UTF-8")]) from error


def _missing(found: list[str]) -> list[str]:
    return [name for name in HEADER if name not in found]


def _extra(found: list[str]) -> list[str]:
    return [name for name in found if name not in HEADER]


def _row(number: int, record: list[str], case: Case, issues: list[CountIssue]) -> CountRow | None:
    """La fila validada, o None si tiene problemas (que se agregan a ``issues``)."""
    if len(record) != len(HEADER):
        issues.append(
            CountIssue(
                number,
                None,
                f"la fila tiene {len(record)} campos y se esperan {len(HEADER)}",
            )
        )
        return None
    values = dict(zip(HEADER, record, strict=True))
    before = len(issues)
    for name in HEADER:
        if not values[name].strip():
            issues.append(CountIssue(number, name, "campo obligatorio vacío"))
    if values["case_id"] and values["case_id"] != case.case_id:
        issues.append(
            CountIssue(
                number,
                "case_id",
                f"el aforo es del caso {values['case_id']!r} y se importa en {case.case_id!r}",
            )
        )
    if values["origin"] and values["origin"] != case.origin:
        issues.append(
            CountIssue(
                number,
                "origin",
                f"el origen es {values['origin']!r} y el caso es {case.origin!r}",
            )
        )
    if values["quality_state"] and values["quality_state"] not in QUALITY_STATES:
        issues.append(
            CountIssue(
                number,
                "quality_state",
                f"valor no admitido {values['quality_state']!r}; valores posibles: "
                f"{', '.join(sorted(QUALITY_STATES))}",
            )
        )
    if values["movement_id"] and values["movement_id"] not in {m.id for m in case.movements}:
        issues.append(
            CountIssue(
                number,
                "movement_id",
                f"el movimiento {values['movement_id']!r} no existe en el caso",
            )
        )
    if values["vehicle_class"] and values["vehicle_class"] not in case.vehicle_classes:
        issues.append(
            CountIssue(
                number,
                "vehicle_class",
                f"la clase {values['vehicle_class']!r} no existe en el caso",
            )
        )
    start = _instant(number, "start", values["start"], issues)
    end = _instant(number, "end", values["end"], issues)
    if start is not None and end is not None and end <= start:
        issues.append(CountIssue(number, "end", "el fin debe ser posterior al inicio"))
    count = _count(number, values["count"], issues)
    if len(issues) != before or start is None or end is None or count is None:
        return None
    return CountRow(
        line=number,
        observation_id=values["observation_id"],
        source_id=values["source_id"],
        start=start,
        end=end,
        movement_id=values["movement_id"],
        vehicle_class=values["vehicle_class"],
        count=count,
    )


def _instant(number: int, field: str, text: str, issues: list[CountIssue]) -> datetime | None:
    if not text.strip():
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        issues.append(
            CountIssue(number, field, f"fecha no válida {text!r}; se espera ISO 8601 con zona")
        )
        return None
    if moment.tzinfo is None:
        issues.append(CountIssue(number, field, f"la fecha {text!r} no tiene zona horaria"))
        return None
    return moment


def _count(number: int, text: str, issues: list[CountIssue]) -> int | None:
    if not text.strip():
        return None
    if INTEGER.fullmatch(text) is None:
        issues.append(
            CountIssue(
                number,
                "count",
                f"el conteo {text!r} debe ser un entero no negativo (sin signo menos ni decimales)",
            )
        )
        return None
    return int(text)
