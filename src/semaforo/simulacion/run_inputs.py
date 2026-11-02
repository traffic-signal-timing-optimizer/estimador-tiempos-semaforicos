"""Ejecución de una carpeta de entradas de DEV06 (DEV07 F1; decisiones D1 a D3 y D10 de F0).

``run_inputs`` hace, en orden:

1. **Comprueba la carpeta antes de lanzar SUMO** (D2): el manifiesto es válido; la carpeta tiene
   exactamente los archivos del manifiesto, sin enlaces ni subcarpetas, y cada uno con su huella;
   y la configuración de SUMO dice lo mismo que el manifiesto (inicio, fin, paso, semilla y
   archivos). ``manifiesto.json`` no puede llevar su propia huella: esta comparación cierra ese
   hueco. Una carpeta alterada no se ejecuta.
2. **Ejecuta con el corredor de DEV00** (D1, D3), con el fin de la simulación, la semilla, el
   escenario y la versión del caso tomados del manifiesto. Si la carpeta declara una zona de
   medición (manifiesto 1.1.0, ADR11), SUMO escribe también la FCD de la zona y los viajes que
   nunca entraron.
3. **Concilia la cohorte antes de publicar** (D10): vuelve a comprobar la copia de las entradas
   que usó SUMO y agrega a ``outputs/`` la tabla de cohorte y sus conteos. Si la conciliación
   falla, la corrida queda ``failed`` y sin métricas. Vehículos sin terminar o que no entraron no
   la hacen fallar: se cuentan.
"""

import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from semaforo.caso.json_input import read_json
from semaforo.caso.xml_input import parse_root
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.errors import ErrorCode
from semaforo.simulacion.prepare import (
    CONFIG_FILE,
    DEMAND_FILE,
    MANIFEST_FILE,
    ZONE_FILE,
    InputsManifest,
    zone_file_bytes,
)
from semaforo.simulacion.reconcile import OutcomeCount, reconcile, reconciliation_csv
from semaforo.simulacion.runner import (
    MAX_CONFIG_BYTES,
    TRIPINFO,
    RunLimits,
    SimulacionError,
    SimulationResult,
    run_simulation,
)
from semaforo.trazabilidad.hashing import sha256_file
from semaforo.trazabilidad.store import RunSpec, utc_now

__all__ = [
    "CONCILIATION_SUMMARY",
    "CONCILIATION_TABLE",
    "ConciliationSummary",
    "run_inputs",
    "verify_inputs",
    "zone_of",
]

CONCILIATION_TABLE = "cohorte_conciliada.csv"
CONCILIATION_SUMMARY = "conciliacion.json"
INPUTS = "inputs"
OUTPUTS = "outputs"


class ConciliationSummary(FrozenModel):
    """Conteos de la conciliación de una corrida (``outputs/conciliacion.json``)."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    scenario_id: str
    vehicles_total: int
    requested: int
    finished: int
    unfinished: int
    not_inserted: int
    counts: list[OutcomeCount]


def _error(code: ErrorCode, message: str, field: str | None = None) -> SimulacionError:
    return SimulacionError(code, message, field)


def _manifest(folder: Path) -> InputsManifest:
    try:
        return InputsManifest.model_validate(read_json(folder / MANIFEST_FILE, "manifiesto"))
    except ValidationError as error:
        raise _error(
            ErrorCode.INPUT_SCHEMA,
            f"el manifiesto de las entradas no es válido ({error.error_count()} problemas)",
            MANIFEST_FILE,
        ) from None


def _check_files(folder: Path, manifest: InputsManifest) -> None:
    """La carpeta tiene exactamente los archivos del manifiesto, cada uno con su huella."""
    present: dict[str, str] = {}
    for path in sorted(folder.iterdir()):
        if path.is_symlink() or path.is_junction() or not path.is_file():
            raise _error(
                ErrorCode.PATH_NOT_ALLOWED,
                "la carpeta de entradas solo puede tener archivos, sin enlaces ni subcarpetas",
                path.name,
            )
        if path.name != MANIFEST_FILE:
            present[path.name] = sha256_file(path)
    extra = sorted(present.keys() - manifest.files.keys())
    missing = sorted(manifest.files.keys() - present.keys())
    if extra or missing:
        detail = f"sobra {extra[0]}" if extra else f"falta {missing[0]}"
        raise _error(
            ErrorCode.HASH_MISMATCH,
            f"la carpeta de entradas no tiene los archivos de su manifiesto: {detail}",
            extra[0] if extra else missing[0],
        )
    changed = [name for name in sorted(present) if present[name] != manifest.files[name]]
    if changed:
        raise _error(
            ErrorCode.HASH_MISMATCH,
            f"la carpeta de entradas fue alterada: {changed[0]} no tiene la huella del manifiesto",
            changed[0],
        )


def _config_values(root_path: Path, manifest: InputsManifest) -> dict[str, str]:
    root = parse_root(
        root_path, MAX_CONFIG_BYTES, frozenset({"configuration"}), "configuración de SUMO"
    )
    found: dict[str, str] = {}
    for section, option in (
        ("input", "net-file"),
        ("input", "route-files"),
        ("input", "additional-files"),
        ("time", "begin"),
        ("time", "end"),
        ("time", "step-length"),
        ("random_number", "seed"),
    ):
        element = root.find(f"{section}/{option}")
        value = None if element is None else element.get("value")
        if value is None:
            raise _error(
                ErrorCode.HASH_MISMATCH,
                f"la configuración de SUMO no declara {option}",
                manifest.entry_config,
            )
        found[option] = value
    return found


def _same_number(text: str, expected: float) -> bool:
    try:
        return float(text) == expected
    except ValueError:
        return False


def _check_config(folder: Path, manifest: InputsManifest) -> None:
    """La configuración de SUMO dice lo mismo que el manifiesto."""
    if manifest.entry_config != CONFIG_FILE:
        raise _error(
            ErrorCode.PATH_NOT_ALLOWED,
            "el manifiesto apunta a una configuración que no es la de la carpeta de entradas",
            "entry_config",
        )
    found = _config_values(folder / CONFIG_FILE, manifest)
    times = manifest.times
    expected: dict[str, tuple[str, Callable[[str], bool]]] = {
        "net-file": (manifest.network.file, lambda text: text == manifest.network.file),
        "route-files": (DEMAND_FILE, lambda text: text == DEMAND_FILE),
        "additional-files": (manifest.program.file, lambda text: text == manifest.program.file),
        "begin": (f"{times.begin_s:g}", lambda text: _same_number(text, times.begin_s)),
        "end": (f"{times.end_s:g}", lambda text: _same_number(text, times.end_s)),
        "step-length": (
            f"{times.step_length_s:g}",
            lambda text: _same_number(text, times.step_length_s),
        ),
        "seed": (
            str(manifest.seeds.sumo_seed),
            lambda text: _same_number(text, manifest.seeds.sumo_seed),
        ),
    }
    for option, (shown, matches) in expected.items():
        if not matches(found[option]):
            raise _error(
                ErrorCode.HASH_MISMATCH,
                f"la configuración de SUMO dice {option}={found[option]} y el manifiesto {shown}",
                manifest.entry_config,
            )


def _check_zone(folder: Path, manifest: InputsManifest) -> None:
    """La zona de medición del archivo es la del manifiesto (ADR11); sin zona, no hay archivo."""
    declared = bool(manifest.measurement_edges)
    if declared != (ZONE_FILE in manifest.files):
        raise _error(
            ErrorCode.HASH_MISMATCH,
            "el manifiesto y los archivos no coinciden en la zona de medición",
            ZONE_FILE,
        )
    access = manifest.measurement_access
    if access and set(access) != set(manifest.measurement_edges):
        raise _error(
            ErrorCode.HASH_MISMATCH,
            "el acceso de las calles de la zona no coincide con sus calles",
            MANIFEST_FILE,
        )
    if declared and (folder / ZONE_FILE).read_bytes() != zone_file_bytes(
        manifest.measurement_edges
    ):
        raise _error(
            ErrorCode.HASH_MISMATCH,
            "las calles de la zona de medición no son las del manifiesto",
            ZONE_FILE,
        )


def zone_of(manifest: InputsManifest) -> str | None:
    """Archivo de la zona de medición de una carpeta de entradas, o None si no la declara."""
    return ZONE_FILE if manifest.measurement_edges else None


def verify_inputs(folder: Path) -> InputsManifest:
    """Manifiesto de la carpeta de entradas ``folder``, después de comprobarla entera (D2).

    Raises:
        SimulacionError: PATH_NOT_ALLOWED si la carpeta es un enlace o tiene enlaces o
            subcarpetas; INPUT_SCHEMA si no existe o su manifiesto no es válido; HASH_MISMATCH si
            sobran, faltan o cambiaron archivos, o si la configuración o la zona de medición no
            coinciden con el manifiesto.
        CasoError: si el manifiesto o la configuración no se pueden leer.
    """
    if folder.is_symlink() or folder.is_junction():
        raise _error(
            ErrorCode.PATH_NOT_ALLOWED, "la carpeta de entradas es un enlace o una unión", "inputs"
        )
    if not folder.is_dir():
        raise _error(ErrorCode.INPUT_SCHEMA, "no existe la carpeta de entradas", "inputs")
    manifest = _manifest(folder)
    _check_files(folder, manifest)
    _check_config(folder, manifest)
    _check_zone(folder, manifest)
    return manifest


def _conciliation(manifest: InputsManifest) -> Callable[[Path], Mapping[str, bytes]]:
    """Paso previo a publicar: concilia la cohorte con la copia de las entradas que usó SUMO."""

    def finalize(run_folder: Path) -> Mapping[str, bytes]:
        copied = run_folder / INPUTS
        if verify_inputs(copied) != manifest:
            raise _error(
                ErrorCode.HASH_MISMATCH,
                "la copia de las entradas de la corrida no es la que se comprobó",
                INPUTS,
            )
        result = reconcile(copied, run_folder / OUTPUTS / TRIPINFO)
        summary = ConciliationSummary(
            scenario_id=manifest.scenario_id,
            vehicles_total=len(result.outcomes),
            requested=result.requested,
            finished=result.finished,
            unfinished=result.unfinished,
            not_inserted=result.not_inserted,
            counts=result.counts,
        )
        text = json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=2)
        return {
            CONCILIATION_TABLE: reconciliation_csv(result),
            CONCILIATION_SUMMARY: (text + "\n").encode("utf-8"),
        }

    return finalize


def run_inputs(  # noqa: PLR0913  (los opcionales son de solo palabra clave)
    inputs_dir: Path,
    runs_root: Path,
    *,
    limits: RunLimits | None = None,
    sumo: Path | None = None,
    clock: Callable[[], datetime] = utc_now,
    cancel: threading.Event | None = None,
    retry_of: str | None = None,
) -> SimulationResult:
    """Ejecuta la carpeta de entradas ``inputs_dir`` y publica la corrida en ``runs_root``.

    El fin de la simulación sale del manifiesto: el ``end_s`` de ``limits`` no se usa. Los demás
    límites (tiempo real, topes de salidas y de memoria, largo de rutas) sí. Con ``cancel`` se puede
    cancelar la corrida: queda publicada como ``cancelled`` y sin conciliación. Con ``retry_of``
    la corrida es el reintento de una anterior ``failed``, ``cancelled`` o interrumpida del mismo
    caso, versión y escenario: es una corrida nueva y la anterior no se toca.

    Raises:
        SimulacionError o CasoError: antes de ejecutar nada, si la carpeta no pasa
            ``verify_inputs``; además, lo que lanza ``run_simulation`` antes de ejecutar.
    """
    manifest = verify_inputs(inputs_dir)
    spec = RunSpec(
        kind="simulation",
        case_id=manifest.case_id,
        case_version=manifest.case_version,
        scenario_id=manifest.scenario_id,
        seed=manifest.seeds.sumo_seed,
        retry_of=retry_of,
    )
    return run_simulation(
        inputs_dir,
        manifest.entry_config,
        runs_root,
        spec,
        limits=replace(limits or RunLimits(), end_s=manifest.times.end_s),
        sumo=sumo,
        declared_vehicles=manifest.vehicles.total,
        clock=clock,
        finalize=_conciliation(manifest),
        cancel=cancel,
        zone_file=zone_of(manifest),
    )
