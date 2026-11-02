"""Llegadas de cada escenario en un archivo fijo, iguales para todos los comparadores (DEV11 F3).

Decisión D8 de F0. La cohorte de DEV06 (``semaforo.simulacion.cohort``) dice qué vehículos se
simularán: identificador, movimiento, clase y hora de salida. Aquí se escribe esa lista en un
archivo de texto fijo (``demanda/<escenario>.csv``) y el escenario lo enlaza con su huella en
``demand_artifact``. Quien compare alternativas lee el archivo y comprueba su huella: ve siempre los
mismos vehículos, y cualquier cambio se detecta.

Formato (UTF-8, saltos de línea ``\\n``, sin comillas ni comas dentro de los campos)::

    vehicle_id,movement_id,vehicle_class,depart_s,in_cohort
    N_S.car.1,N_S,car,12.0,true

Los vehículos van en el orden de la cohorte: por hora de salida y luego por identificador.
``in_cohort`` es ``false`` para los del calentamiento. Un conjunto no puede pasar de
``MAX_SET_VEHICLES`` vehículos en total, para no llenar la memoria al publicarlo.
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

from semaforo.datos.scenarios import GeneratedScenario
from semaforo.dominio.case import Artifact, Case
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.dominio.scenario import Scenario
from semaforo.simulacion.cohort import MAX_VEHICLES, CohortError, CohortVehicle, generate_cohort
from semaforo.trazabilidad.hashing import sha256_bytes

__all__ = [
    "DEMAND_HEADER",
    "MAX_DEMAND_BYTES",
    "MAX_SET_VEHICLES",
    "MaterializedDemand",
    "ScenarioDemandError",
    "demand_path",
    "load_demand",
    "materialize_all",
    "materialize_demand",
    "parse_demand",
    "render_demand",
]

DEMAND_HEADER = "vehicle_id,movement_id,vehicle_class,depart_s,in_cohort"
MAX_SET_VEHICLES = 2_000_000
MAX_DEMAND_BYTES = 32 * 1024 * 1024
FIELDS = 5
_VEHICLE_ID = re.compile(r"[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)+")
_NAME = re.compile(r"[A-Za-z0-9_-]+")
_BOOLEANS = {"true": True, "false": False}


class ScenarioDemandError(DomainError):
    """El archivo de llegadas no es válido, no coincide con su escenario o el conjunto es enorme."""

    def __init__(self, code: ErrorCode, message: str, field: str | None = None) -> None:
        super().__init__(code, message, field)


def demand_path(scenario_id: str) -> str:
    """Ruta del archivo de llegadas dentro de la carpeta del conjunto."""
    return f"demanda/{scenario_id}.csv"


def render_demand(vehicles: Sequence[CohortVehicle]) -> bytes:
    """El texto fijo de las llegadas, en el orden recibido (el de la cohorte)."""
    lines = [DEMAND_HEADER]
    lines.extend(
        f"{v.vehicle_id},{v.movement_id},{v.vehicle_class},{v.depart_s!r},"
        f"{'true' if v.in_cohort else 'false'}"
        for v in vehicles
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def parse_demand(data: bytes) -> tuple[CohortVehicle, ...]:
    """Las llegadas de un archivo, comprobando formato, orden e identificadores únicos.

    Raises:
        ScenarioDemandError: INPUT_SCHEMA si el archivo es demasiado grande, no es UTF-8 limpio, el
            encabezado no es el esperado, una fila no tiene cinco campos válidos, hay un
            identificador repetido, las filas no están en orden o hay demasiados vehículos.
    """
    if len(data) > MAX_DEMAND_BYTES:
        raise _invalid("el archivo de llegadas es demasiado grande")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise _invalid("el archivo de llegadas no es UTF-8") from None
    if text.startswith("\N{ZERO WIDTH NO-BREAK SPACE}") or "\r" in text or not text.endswith("\n"):
        raise _invalid("el archivo de llegadas debe tener saltos de línea \\n y terminar con uno")
    lines = text[:-1].split("\n")
    if lines[0] != DEMAND_HEADER:
        raise _invalid("el encabezado de las llegadas no es el esperado", "línea 1")
    if len(lines) - 1 > MAX_VEHICLES:
        raise _invalid(f"las llegadas pasan del máximo de {MAX_VEHICLES} vehículos")
    vehicles = tuple(_vehicle(line, number) for number, line in enumerate(lines[1:], start=2))
    _check_order(vehicles)
    return vehicles


def _invalid(message: str, field: str | None = None) -> ScenarioDemandError:
    return ScenarioDemandError(ErrorCode.INPUT_SCHEMA, message, field)


def _vehicle(line: str, number: int) -> CohortVehicle:
    where = f"línea {number}"
    parts = line.split(",")
    if len(parts) != FIELDS:
        raise _invalid(f"la fila debe tener {FIELDS} campos y tiene {len(parts)}", where)
    vehicle_id, movement_id, vehicle_class, depart, in_cohort = parts
    if _VEHICLE_ID.fullmatch(vehicle_id) is None:
        raise _invalid("identificador de vehículo no válido", where)
    for name in (movement_id, vehicle_class):
        if _NAME.fullmatch(name) is None:
            raise _invalid("movimiento o clase no válidos", where)
    try:
        depart_s = float(depart)
    except ValueError:
        raise _invalid("la hora de salida no es un número", where) from None
    if not math.isfinite(depart_s) or depart_s < 0:
        raise _invalid("la hora de salida debe ser un número finito mayor o igual que 0", where)
    if in_cohort not in _BOOLEANS:
        raise _invalid("in_cohort debe ser true o false", where)
    return CohortVehicle(vehicle_id, movement_id, vehicle_class, depart_s, _BOOLEANS[in_cohort])


def _check_order(vehicles: tuple[CohortVehicle, ...]) -> None:
    seen: set[str] = set()
    previous: tuple[float, str] | None = None
    for number, vehicle in enumerate(vehicles, start=2):
        if vehicle.vehicle_id in seen:
            raise _invalid(f"el vehículo «{vehicle.vehicle_id}» está repetido", f"línea {number}")
        seen.add(vehicle.vehicle_id)
        key = (vehicle.depart_s, vehicle.vehicle_id)
        if previous is not None and key < previous:
            raise _invalid(
                "las filas deben ir por hora de salida y luego por identificador", f"línea {number}"
            )
        previous = key


@dataclass(frozen=True)
class MaterializedDemand:
    """Un escenario con su archivo de llegadas.

    ``scenario`` ya lleva ``demand_artifact`` (ruta y huella de ``data``). ``vehicles`` cuenta
    todos los vehículos del archivo y ``measured`` los de la cohorte (sin el calentamiento).
    """

    scenario: Scenario
    data: bytes
    path: str
    vehicles: int
    measured: int


def materialize_demand(member: GeneratedScenario, case: Case) -> MaterializedDemand:
    """Genera la cohorte del escenario, la escribe en texto fijo y enlaza el archivo.

    Raises:
        ScenarioDemandError: INPUT_SCHEMA si el escenario pide demasiados vehículos o si ya trae un
            archivo enlazado.
        ScenarioInvalidError: si el escenario no encaja con el caso.
    """
    scenario = member.scenario
    if scenario.demand_artifact is not None:
        raise _invalid("el escenario ya tiene un archivo de llegadas", scenario.scenario_id)
    try:
        cohort = generate_cohort(scenario, case)
    except CohortError as error:
        raise _invalid(f"{scenario.scenario_id}: {error.message}", scenario.scenario_id) from None
    data = render_demand(cohort.vehicles)
    path = demand_path(scenario.scenario_id)
    artifact = Artifact(
        artifact_id=f"{scenario.scenario_id}-demand", path=path, sha256=sha256_bytes(data)
    )
    linked = scenario.model_copy(update={"demand_artifact": artifact})
    return MaterializedDemand(
        scenario=linked,
        data=data,
        path=path,
        vehicles=len(cohort.vehicles),
        measured=len(cohort.measured),
    )


def materialize_all(
    members: Sequence[GeneratedScenario], case: Case, max_vehicles: int = MAX_SET_VEHICLES
) -> list[MaterializedDemand]:
    """Las llegadas de todos los escenarios, parando si el conjunto pasa de ``max_vehicles``.

    Raises:
        ScenarioDemandError: INPUT_SCHEMA si el total de vehículos supera ``max_vehicles``, además
            de lo que lanza ``materialize_demand``.
    """
    result: list[MaterializedDemand] = []
    total = 0
    for member in members:
        item = materialize_demand(member, case)
        total += item.vehicles
        if total > max_vehicles:
            raise _invalid(
                f"el conjunto pide más de {max_vehicles} vehículos en total (con "
                f"{member.scenario.scenario_id} ya van {total})",
                member.scenario.scenario_id,
            )
        result.append(item)
    return result


def load_demand(scenario: Scenario, data: bytes) -> tuple[CohortVehicle, ...]:
    """Las llegadas de ``data`` si son las del escenario: huella, formato y coherencia.

    Es lo que usa cada comparador: con el mismo escenario y los mismos bytes, todos obtienen los
    mismos vehículos.

    Raises:
        ScenarioDemandError: INPUT_SCHEMA si el escenario no enlaza un archivo, el formato no es
            válido, hay un vehículo de un movimiento que el escenario no tiene o su marca de
            cohorte no corresponde a su hora de salida; HASH_MISMATCH si la huella no coincide.
    """
    artifact = scenario.demand_artifact
    if artifact is None:
        raise _invalid("el escenario no tiene archivo de llegadas", scenario.scenario_id)
    if sha256_bytes(data) != artifact.sha256:
        raise ScenarioDemandError(
            ErrorCode.HASH_MISMATCH, "las llegadas no coinciden con su huella", artifact.path
        )
    vehicles = parse_demand(data)
    movements = {row.movement_id for row in scenario.request.demand}
    for number, vehicle in enumerate(vehicles, start=2):
        where = f"línea {number}"
        if vehicle.movement_id not in movements:
            raise _invalid(f"el escenario no tiene el movimiento «{vehicle.movement_id}»", where)
        if vehicle.in_cohort != (vehicle.depart_s >= scenario.warmup_s):
            raise _invalid("la marca de cohorte no corresponde a la hora de salida", where)
    return vehicles
