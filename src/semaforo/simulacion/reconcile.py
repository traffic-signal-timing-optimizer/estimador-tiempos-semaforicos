"""Conciliación de la cohorte con los viajes de SUMO (DEV06 F3, decisión D20, QA25).

Cruza, por identificador, los vehículos que se pidieron (``cohorte.csv`` de la carpeta de entradas)
con los viajes que SUMO escribió (``tripinfo.xml`` de la corrida) y deja a cada vehículo en uno de
tres estados:

- ``finished``: llegó a su destino (``arrival`` mayor o igual que 0).
- ``unfinished``: entró a la red pero seguía en ella al terminar la simulación (``arrival`` -1).
- ``not_inserted``: no tiene viaje; nunca entró a la red.

Nadie se excluye sin registro: la suma de los tres estados es el número pedido, por movimiento y
clase y en total, y cualquier desajuste con el manifiesto o con SUMO es un error. Aquí no se calcula
ninguna métrica (demora, colas): eso es de DEV19.

Lo normal es conciliar una corrida publicada (``reconcile_run``): comprueba que terminó bien, que
no está alterada y que se hizo con estas mismas entradas. ``reconcile`` cruza cualquier
``tripinfo.xml`` y solo se usa si ya se sabe de qué corrida viene.
"""

import csv
import io
import re
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from semaforo.caso.errors import CasoError
from semaforo.caso.json_input import read_json, read_text_file
from semaforo.caso.xml_input import optional_number, parse_root, required
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.simulacion.cohort import SAFE_ID
from semaforo.simulacion.prepare import (
    COHORT_FILE,
    COHORT_HEADER,
    MANIFEST_FILE,
    InputsManifest,
)
from semaforo.trazabilidad.hashing import sha256_file
from semaforo.trazabilidad.store import read_run

__all__ = [
    "MAX_COHORT_BYTES",
    "MAX_TRIPINFO_BYTES",
    "OutcomeCount",
    "Reconciliation",
    "ReconciliationError",
    "Status",
    "VehicleOutcome",
    "reconcile",
    "reconcile_run",
    "reconciliation_csv",
]

# 200 000 vehículos (límite de la cohorte) por unos 300 bytes de fila, con holgura.
MAX_COHORT_BYTES = 128 * 1024 * 1024
MAX_TRIPINFO_BYTES = 512 * 1024 * 1024
CSV_DELIMITER = ";"
# Los vehículos llevan puntos (``M01.passenger.1``); el movimiento y la clase no.
SAFE_VEHICLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
YES = "sí"
NO = "no"
TABLE_HEADER = [
    "vehicle_id",
    "movement_id",
    "vehicle_class",
    "en_cohorte",
    "depart_programada_s",
    "estado",
    "entrada_real_s",
    "llegada_s",
]
Status = Literal["finished", "unfinished", "not_inserted"]


class ReconciliationError(DomainError):
    """La cohorte, su manifiesto o los viajes de SUMO no se pueden conciliar."""


class VehicleOutcome(FrozenModel):
    """Qué pasó con un vehículo pedido."""

    vehicle_id: str
    movement_id: str
    vehicle_class: str
    in_cohort: bool
    scheduled_s: float
    status: Status
    inserted_s: float | None
    arrival_s: float | None


class OutcomeCount(FrozenModel):
    """Vehículos de la cohorte de un movimiento y clase, por estado."""

    movement_id: str
    vehicle_class: str
    requested: int = Field(ge=0)
    finished: int = Field(ge=0)
    unfinished: int = Field(ge=0)
    not_inserted: int = Field(ge=0)


class Reconciliation(FrozenModel):
    """Resultado de la conciliación: cada vehículo pedido y los conteos de la cohorte."""

    outcomes: list[VehicleOutcome]
    counts: list[OutcomeCount]
    requested: int = Field(ge=0)
    finished: int = Field(ge=0)
    unfinished: int = Field(ge=0)
    not_inserted: int = Field(ge=0)


def _error(code: ErrorCode, message: str, field: str | None = None) -> ReconciliationError:
    return ReconciliationError(code, message, field)


def _identifier(cell: str, column: str, line: int, pattern: re.Pattern[str] = SAFE_ID) -> str:
    """Valor de una celda de identificador, que la planilla guarda como ``="valor"``."""
    if not (cell.startswith('="') and cell.endswith('"') and len(cell) >= len('=""')):
        raise _error(
            ErrorCode.INPUT_SCHEMA,
            f"la cohorte no es válida en la línea {line}: «{column}» no tiene el formato esperado",
            COHORT_FILE,
        )
    value = cell[2:-1].replace('""', '"')
    if pattern.fullmatch(value) is None:
        raise _error(
            ErrorCode.INPUT_SCHEMA,
            f"la cohorte no es válida en la línea {line}: «{column}» tiene caracteres no "
            "permitidos",
            COHORT_FILE,
        )
    return value


def _manifest(folder: Path) -> InputsManifest:
    try:
        return InputsManifest.model_validate(read_json(folder / MANIFEST_FILE, "manifiesto"))
    except ValidationError as error:
        raise _error(
            ErrorCode.INPUT_SCHEMA,
            f"el manifiesto de las entradas no es válido ({error.error_count()} problemas)",
            MANIFEST_FILE,
        ) from None


def _read_cohort(folder: Path, manifest: InputsManifest) -> list[VehicleOutcome]:
    """Vehículos pedidos, en el orden de la planilla, todos como ``not_inserted`` por ahora."""
    path = folder / COHORT_FILE
    text = read_text_file(path, "cohorte", MAX_COHORT_BYTES)
    if sha256_file(path) != manifest.files.get(COHORT_FILE):
        raise _error(
            ErrorCode.HASH_MISMATCH,
            "la planilla de la cohorte no tiene la huella de su manifiesto",
            COHORT_FILE,
        )
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=CSV_DELIMITER))
    if not rows or rows[0] != COHORT_HEADER:
        raise _error(
            ErrorCode.INPUT_SCHEMA, "la cohorte no tiene el encabezado esperado", COHORT_FILE
        )
    vehicles: list[VehicleOutcome] = []
    seen: set[str] = set()
    for line, row in enumerate(rows[1:], start=2):
        if len(row) != len(COHORT_HEADER):
            raise _error(
                ErrorCode.INPUT_SCHEMA,
                f"la cohorte no es válida en la línea {line}: tiene {len(row)} columnas",
                COHORT_FILE,
            )
        vehicle_id = _identifier(row[0], "vehicle_id", line, SAFE_VEHICLE_ID)
        if vehicle_id in seen:
            raise _error(
                ErrorCode.INPUT_SCHEMA,
                f"la cohorte repite el vehículo «{vehicle_id}»",
                COHORT_FILE,
            )
        seen.add(vehicle_id)
        if row[7] not in (YES, NO):
            raise _error(
                ErrorCode.INPUT_SCHEMA,
                f"la cohorte no es válida en la línea {line}: «en_cohorte» debe ser {YES} o {NO}",
                COHORT_FILE,
            )
        try:
            scheduled = float(row[5])
        except ValueError:
            raise _error(
                ErrorCode.INPUT_SCHEMA,
                f"la cohorte no es válida en la línea {line}: «depart_s» no es un número",
                COHORT_FILE,
            ) from None
        vehicles.append(
            VehicleOutcome(
                vehicle_id=vehicle_id,
                movement_id=_identifier(row[1], "movement_id", line),
                vehicle_class=_identifier(row[2], "vehicle_class", line),
                in_cohort=row[7] == YES,
                scheduled_s=scheduled,
                status="not_inserted",
                inserted_s=None,
                arrival_s=None,
            )
        )
    _check_against_manifest(vehicles, manifest)
    return vehicles


def _check_against_manifest(vehicles: list[VehicleOutcome], manifest: InputsManifest) -> None:
    """La planilla tiene los mismos vehículos que declara el manifiesto, por movimiento y clase."""
    declared = manifest.vehicles
    cohort = sum(1 for vehicle in vehicles if vehicle.in_cohort)
    if (len(vehicles), cohort) != (declared.total, declared.cohort):
        raise _error(
            ErrorCode.HASH_MISMATCH,
            f"la planilla tiene {len(vehicles)} vehículos ({cohort} de cohorte) y el manifiesto "
            f"declara {declared.total} ({declared.cohort})",
            COHORT_FILE,
        )
    found: dict[tuple[str, str], list[int]] = {}
    for vehicle in vehicles:
        pair = found.setdefault((vehicle.movement_id, vehicle.vehicle_class), [0, 0])
        pair[1 if vehicle.in_cohort else 0] += 1
    expected = {
        (count.movement_id, count.vehicle_class): [count.warmup, count.measured]
        for count in declared.counts
        if count.warmup or count.measured
    }
    if found != expected:
        raise _error(
            ErrorCode.HASH_MISMATCH,
            "los vehículos de la planilla por movimiento y clase no coinciden con el manifiesto",
            COHORT_FILE,
        )


def _trips_by_id(tripinfo: Path) -> dict[str, tuple[float | None, float | None]]:
    """Salida (``depart``, ``arrival``) de cada viaje de ``tripinfo``, por identificador."""
    if tripinfo.is_symlink() or tripinfo.is_junction():
        raise CasoError(
            ErrorCode.PATH_NOT_ALLOWED,
            "tripinfo: el archivo es un enlace o una unión",
            tripinfo.name,
        )
    try:
        root = parse_root(tripinfo, MAX_TRIPINFO_BYTES, frozenset({"tripinfos"}), "tripinfo")
        found = [
            (
                required(trip, "id"),
                (optional_number(trip, "depart"), optional_number(trip, "arrival")),
            )
            for trip in root.findall("tripinfo")
        ]
    except DomainError as invalid:
        raise _error(ErrorCode.OUTPUT_INVALID, invalid.message, tripinfo.name) from invalid
    trips: dict[str, tuple[float | None, float | None]] = {}
    for trip_id, times in found:
        if trip_id in trips:
            raise _error(
                ErrorCode.OUTPUT_INVALID,
                f"SUMO escribió dos viajes del vehículo «{trip_id}»",
                tripinfo.name,
            )
        trips[trip_id] = times
    return trips


def _apply_trips(vehicles: list[VehicleOutcome], tripinfo: Path) -> list[VehicleOutcome]:
    """Estado de cada vehículo según los viajes de SUMO."""
    trips = _trips_by_id(tripinfo)
    known = {vehicle.vehicle_id for vehicle in vehicles}
    unknown = sorted(trips.keys() - known)
    if unknown:
        raise _error(
            ErrorCode.OUTPUT_INVALID,
            f"SUMO escribió {len(unknown)} viajes de vehículos que no se pidieron (el primero: "
            f"«{unknown[0]}»)",
            tripinfo.name,
        )
    result: list[VehicleOutcome] = []
    for vehicle in vehicles:
        trip = trips.get(vehicle.vehicle_id)
        if trip is None:
            result.append(vehicle)
            continue
        inserted, arrival = trip
        finished = arrival is not None and arrival >= 0
        result.append(
            vehicle.model_copy(
                update={
                    "status": "finished" if finished else "unfinished",
                    "inserted_s": inserted,
                    "arrival_s": arrival if finished else None,
                }
            )
        )
    return result


def _count(outcomes: list[VehicleOutcome]) -> list[OutcomeCount]:
    table: dict[tuple[str, str], dict[Status, int]] = {}
    for vehicle in outcomes:
        if vehicle.in_cohort:
            states = table.setdefault(
                (vehicle.movement_id, vehicle.vehicle_class),
                {"finished": 0, "unfinished": 0, "not_inserted": 0},
            )
            states[vehicle.status] += 1
    return [
        OutcomeCount(
            movement_id=movement,
            vehicle_class=name,
            requested=sum(states.values()),
            finished=states["finished"],
            unfinished=states["unfinished"],
            not_inserted=states["not_inserted"],
        )
        for (movement, name), states in sorted(table.items())
    ]


def reconcile(inputs_dir: Path, tripinfo: Path) -> Reconciliation:
    """Cruza la cohorte de ``inputs_dir`` (carpeta de entradas de F2) con ``tripinfo``.

    La planilla se comprueba contra la huella y los conteos del manifiesto antes de usarla. Los
    vehículos de calentamiento se registran en ``outcomes`` pero no cuentan en la cohorte.

    Raises:
        ReconciliationError: HASH_MISMATCH si la planilla no es la del manifiesto; INPUT_SCHEMA si
            el manifiesto o la planilla no son válidos; OUTPUT_INVALID si el ``tripinfo`` no es
            válido, repite un vehículo o trae uno que no se pidió.
        CasoError: PATH_NOT_ALLOWED si un archivo es un enlace; INPUT_SCHEMA si falta o es
            demasiado grande.
    """
    manifest = _manifest(inputs_dir)
    outcomes = _apply_trips(_read_cohort(inputs_dir, manifest), tripinfo)
    cohort = [vehicle for vehicle in outcomes if vehicle.in_cohort]
    by_status = {
        status: sum(1 for vehicle in cohort if vehicle.status == status)
        for status in ("finished", "unfinished", "not_inserted")
    }
    return Reconciliation(
        outcomes=outcomes,
        counts=_count(outcomes),
        requested=len(cohort),
        finished=by_status["finished"],
        unfinished=by_status["unfinished"],
        not_inserted=by_status["not_inserted"],
    )


def reconcile_run(inputs_dir: Path, runs_root: Path, run_id: str) -> Reconciliation:
    """Concilia la cohorte de ``inputs_dir`` con la corrida ``run_id`` publicada en ``runs_root``.

    Raises:
        ReconciliationError: OUTPUT_INVALID si la corrida no terminó bien (no hay métricas de una
            corrida fallida); HASH_MISMATCH si la corrida se hizo con otras entradas; además lo de
            ``reconcile``.
        TrazabilidadError: si la corrida no existe o fue alterada (``read_run``).
    """
    run = read_run(runs_root, run_id)
    if run.status != "succeeded":
        raise _error(
            ErrorCode.OUTPUT_INVALID,
            f"la corrida terminó en «{run.status}»: no se concilia una corrida que no terminó bien",
            "run_id",
        )
    recorded = {artifact.path.removeprefix("inputs/"): artifact.sha256 for artifact in run.inputs}
    present = {
        path.name: sha256_file(path) for path in sorted(inputs_dir.iterdir()) if path.is_file()
    }
    if present != recorded:
        raise _error(
            ErrorCode.HASH_MISMATCH,
            "la corrida no se hizo con estas entradas: los archivos de la carpeta no coinciden con "
            "los que registró la corrida",
            "run_id",
        )
    return reconcile(inputs_dir, runs_root / run_id / "outputs" / "tripinfo.xml")


def _number(value: float | None) -> str:
    return "" if value is None else f"{value:g}"


def reconciliation_csv(result: Reconciliation) -> bytes:
    """Tabla de cohorte (evidencia de QA25) en el formato de las planillas del equipo."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=CSV_DELIMITER, lineterminator="\r\n")
    writer.writerow(TABLE_HEADER)
    for vehicle in result.outcomes:
        writer.writerow(
            [
                '="' + vehicle.vehicle_id + '"',
                '="' + vehicle.movement_id + '"',
                '="' + vehicle.vehicle_class + '"',
                YES if vehicle.in_cohort else NO,
                _number(vehicle.scheduled_s),
                vehicle.status,
                _number(vehicle.inserted_s),
                _number(vehicle.arrival_s),
            ]
        )
    return buffer.getvalue().encode("utf-8-sig")
