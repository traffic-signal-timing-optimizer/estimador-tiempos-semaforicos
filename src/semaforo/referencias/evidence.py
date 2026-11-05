"""Evidencia de una búsqueda publicada: qué insumos usó y cuál sería su identidad hoy (A01).

``verify_search_evidence`` toma una etiqueta publicada, la bitácora con que se hizo y las carpetas
de entradas y corridas, y comprueba sin escribir nada:

1. que la etiqueta está íntegra (``read_label``) y que la bitácora es la suya;
2. que cada carpeta de entradas anotada está íntegra, que su semilla es la anotada y que cada
   corrida salió de ella;
3. que todas comparten los mismos insumos (caso con su red, escenario con su demanda y sus
   tiempos, rutas, tipos de vehículo y opciones de SUMO) y la misma versión de SUMO;
4. opcionalmente, que volver a medir cada corrida con el protocolo dado da el mismo resultado que
   quedó anotado, que es lo que prueba que ese protocolo es el que se usó.

Con eso, una búsqueda hecha con la identidad 1.0.0 (que solo guardaba nombres) se reexpresa con la
identidad 2.0.0 (que guarda la huella de cada insumo): ``reexpress_identity``. Las huellas salen de
los manifiestos de las propias corridas, no de los archivos de hoy, y se calculan con las mismas
funciones que usa una búsqueda nueva; por eso repetir la búsqueda con el código actual tiene que dar
el mismo identificador. La etiqueta publicada no se toca.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from semaforo.dominio.case import Case, canonical_sha256
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.dominio.protocol import Protocol
from semaforo.dominio.scenario import Scenario
from semaforo.evaluacion.run_metrics import evaluate_run
from semaforo.referencias.errors import ReferenciasError
from semaforo.referencias.evaluation import (
    JOURNAL_VERSION,
    MAX_JOURNAL_BYTES,
    identity_digest,
)
from semaforo.referencias.label import TRACE_FILE, read_label
from semaforo.referencias.selection import seed_outcome
from semaforo.simulacion.prepare import canonical_json_sha256
from semaforo.simulacion.run_inputs import verify_inputs
from semaforo.trazabilidad.fs import read_at_most
from semaforo.trazabilidad.hashing import sha256_file
from semaforo.trazabilidad.manifest import RunManifest
from semaforo.trazabilidad.store import MANIFEST

__all__ = ["EvidenceReport", "reexpress_identity", "verify_search_evidence"]

MAX_TRACE_BYTES = 64 * 1024 * 1024
MAX_RUN_MANIFEST_BYTES = 16 * 1024 * 1024
RUN_INPUTS_ARTIFACT = "inputs/manifiesto.json"
OUTCOME_FIELDS = ("mean_delay_s", "mean_queue_veh", "mean_stops", "teleports", "collisions")
# Lo que debe ser igual en todas las carpetas de entradas. La red va dentro del caso; la demanda,
# los tiempos y la política de frontera, dentro del escenario; la zona de medición sale del caso y
# las rutas. Solo las semillas de SUMO cambian de una carpeta a otra.
SHARED = (
    "case_sha256",
    "scenario_sha256",
    "routes_sha256",
    "vehicle_types_sha256",
    "schema_version",
    "sumo_options",
)


@dataclass(frozen=True)
class EvidenceReport:
    """Lo que se comprobó de una búsqueda publicada. ``problems`` vacío es que todo cuadra."""

    label_id: str
    search_run_id: str
    identity_version: str
    runs: int
    input_folders: int
    sumo_version: str | None
    fingerprints: Mapping[str, object]
    expected_identity: Mapping[str, object]
    expected_search_run_id: str
    expected_label_id: str
    stored_ids_match: bool | None
    recomputed: int
    problems: tuple[str, ...] = field(default=())

    @property
    def ok(self) -> bool:
        return not self.problems

    def to_json(self) -> dict[str, object]:
        return {
            "label_id": self.label_id,
            "search_run_id": self.search_run_id,
            "identity_version": self.identity_version,
            "runs": self.runs,
            "input_folders": self.input_folders,
            "sumo_version": self.sumo_version,
            "fingerprints": dict(self.fingerprints),
            "expected_search_run_id": self.expected_search_run_id,
            "expected_label_id": self.expected_label_id,
            "stored_ids_match": self.stored_ids_match,
            "recomputed": self.recomputed,
            "problems": list(self.problems),
            "ok": self.ok,
        }


def reexpress_identity(
    old: Mapping[str, object], fingerprints: Mapping[str, object]
) -> dict[str, object]:
    """La identidad 2.0.0 de una búsqueda hecha con la 1.0.0, a partir de las huellas probadas.

    Los demás campos (caso, protocolo, semillas, candidatos) se conservan tal cual.
    """
    kept = {name: value for name, value in old.items() if name != "inputs"}
    return {**kept, "journal_version": JOURNAL_VERSION, "inputs": dict(fingerprints)}


def _bad(message: str, field_name: str) -> ReferenciasError:
    return ReferenciasError(ErrorCode.INPUT_SCHEMA, message, field_name)


def _read_json(path: Path, limit: int, what: str) -> Any:  # noqa: ANN401 - JSON sin forma fija
    try:
        with path.open("rb") as stream:
            data = read_at_most(stream, limit + 1)
    except OSError as error:
        raise _bad(f"no se puede leer {what} ({type(error).__name__})", what) from error
    if len(data) > limit:
        raise _bad(f"{what} supera {limit} bytes", what)
    try:
        return json.loads(data)
    except ValueError as error:
        raise _bad(f"{what} no es JSON válido", what) from error


def _journal(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise _bad("la bitácora no es un archivo normal", "journal")
    if path.stat().st_size > MAX_JOURNAL_BYTES:
        raise _bad(f"la bitácora supera {MAX_JOURNAL_BYTES} bytes", "journal")
    records: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_bytes().split(bytes([10]))[:-1], start=1):
        try:
            record = json.loads(line)
        except ValueError as error:
            raise _bad(f"la línea {number} de la bitácora no es JSON", "journal") from error
        if not isinstance(record, dict):
            raise _bad(f"la línea {number} de la bitácora no es un registro", "journal")
        records.append(cast("dict[str, Any]", record))
    if not records or records[0].get("type") != "header":
        raise _bad("la bitácora no empieza con su identidad", "journal")
    return records


def _key(record: Mapping[str, Any]) -> tuple[str, str, int]:
    """Etapa, candidato y semilla de un registro de la bitácora."""
    stage, candidate, seed = record.get("stage"), record.get("candidate_id"), record.get("seed")
    if (
        not isinstance(stage, str)
        or not isinstance(candidate, str)
        or isinstance(seed, bool)
        or not isinstance(seed, int)
    ):
        raise _bad(
            "un registro de la bitácora no dice su etapa, su candidato y su semilla", "journal"
        )
    return stage, candidate, seed


def _outcome(record: Mapping[str, Any]) -> dict[str, Any]:
    outcome = record.get("outcome")
    if not isinstance(outcome, dict):
        raise _bad("un resultado de la bitácora no tiene la forma esperada", "journal")
    return cast("dict[str, Any]", outcome)


def _under(root: Path, text: object, what: str) -> Path:
    if not isinstance(text, str):
        raise _bad(f"{what} no tiene ruta", "journal")
    relative = Path(text)
    if relative.anchor or ".." in relative.parts or not relative.parts:
        raise _bad(f"{what} está fuera de su carpeta", "journal")
    return root / relative


def _run_manifest(runs_root: Path, run_id: object) -> RunManifest:
    path = _under(runs_root, run_id, "una corrida") / MANIFEST
    try:
        with path.open("rb") as stream:
            data = read_at_most(stream, MAX_RUN_MANIFEST_BYTES + 1)
        if len(data) > MAX_RUN_MANIFEST_BYTES:
            raise _bad(f"el manifiesto de {run_id} es demasiado grande", "runs")
        return RunManifest.model_validate_json(data)
    except (OSError, ValidationError) as error:
        raise _bad(f"la corrida {run_id} no se puede leer", "runs") from error


def _compare(recorded: Mapping[str, Any], found: Mapping[str, Any]) -> list[str]:
    return [name for name in OUTCOME_FIELDS if recorded.get(name) != found.get(name)]


def verify_search_evidence(  # noqa: PLR0913, PLR0912, PLR0915  (una comprobación por tema)
    label_folder: Path,
    *,
    journal: Path,
    inputs_root: Path,
    runs_root: Path,
    case: Case,
    protocol: Protocol,
    scenario: Scenario,
    recompute: bool = False,
) -> EvidenceReport:
    """Comprueba una búsqueda publicada contra sus bitácora, entradas y corridas. No escribe nada.

    ``case``, ``protocol`` y ``scenario`` son los archivos con que se quiere explicar la búsqueda:
    si no son los que se usaron, aparece como problema. Con ``recompute`` se vuelve a medir cada
    corrida.

    Raises:
        TrazabilidadError: si la carpeta de la etiqueta no está íntegra.
        ReferenciasError: si la bitácora o el seguimiento no se pueden leer.
    """
    stored = read_label(label_folder)
    trace = _read_json(label_folder / TRACE_FILE, MAX_TRACE_BYTES, TRACE_FILE)
    found = cast("dict[str, Any]", trace).get("identity") if isinstance(trace, dict) else None
    if not isinstance(found, dict):
        raise _bad("el seguimiento de la etiqueta no trae su identidad", TRACE_FILE)
    identity = cast("dict[str, Any]", found)
    records = _journal(journal)
    problems: list[str] = []
    if records[0].get("identity") != identity:
        problems.append("la bitácora no es la de esta etiqueta (su identidad es otra)")

    manifests: dict[tuple[str, str, int], Any] = {}
    sumo_versions: set[str] = set()
    for record in records[1:]:
        if record.get("type") != "inputs":
            continue
        key = _key(record)
        try:
            folder = _under(inputs_root, record.get("inputs_dir"), "una carpeta de entradas")
            manifest = verify_inputs(folder)
        except DomainError as error:
            problems.append(f"entradas {record.get('inputs_dir')}: {error.message}")
            continue
        if manifest.seeds.sumo_seed != key[2]:
            problems.append(f"entradas {folder.name}: su semilla no es la anotada")
        manifests[key] = (folder, manifest)

    runs = 0
    recomputed = 0
    for record in records[1:]:
        if record.get("type") != "seed":
            continue
        outcome = _outcome(record)
        key = _key(record)
        run_id = outcome.get("run_id")
        if run_id is None:
            continue
        runs += 1
        if key not in manifests:
            problems.append(f"la corrida {run_id} no tiene su carpeta de entradas verificada")
            continue
        folder, manifest = manifests[key]
        try:
            run_manifest = _run_manifest(runs_root, run_id)
        except ReferenciasError as error:
            problems.append(error.message)
            continue
        artifacts = {a.artifact_id: a.sha256 for a in run_manifest.inputs}
        if artifacts.get(RUN_INPUTS_ARTIFACT) != sha256_file(folder / "manifiesto.json"):
            problems.append(f"la corrida {run_id} no salió de las entradas anotadas")
        sumo_versions.add(run_manifest.environment.get("sumo", ""))
        if recompute and outcome.get("run_status") == "succeeded":
            try:
                metrics = evaluate_run(
                    folder, runs_root, str(run_id), case, protocol, scenario=scenario
                )
            except DomainError as error:
                problems.append(f"no se pudo volver a medir {run_id}: {error.message}")
                continue
            recomputed += 1
            different = _compare(outcome, seed_outcome(key[2], metrics).to_json())
            if different:
                problems.append(f"volver a medir {run_id} da otro {', '.join(different)}")

    if len(sumo_versions) > 1:
        problems.append("las corridas usaron más de una versión de SUMO")
    sumo = next(iter(sumo_versions), None)

    first = next(iter(manifests.values()), None)
    fingerprints: dict[str, object] = {}
    if first is None:
        problems.append("la bitácora no anota ninguna carpeta de entradas verificable")
    else:
        base = first[1]
        for _, manifest in manifests.values():
            for name in SHARED:
                if getattr(manifest, name) != getattr(base, name):
                    problems.append(f"las carpetas de entradas no comparten {name}")
        fingerprints = {
            "case_sha256": base.case_sha256,
            "network_sha256": base.network.sha256,
            "scenario_sha256": base.scenario_sha256,
            "routes_sha256": base.routes_sha256,
            "vehicle_types_sha256": base.vehicle_types_sha256,
            "protocol_sha256": canonical_json_sha256(protocol.model_dump(mode="json")),
            "inputs_schema_version": base.schema_version,
            "sumo_version": sumo or "",
        }
        if canonical_sha256(case) != base.case_sha256:
            problems.append("el caso dado no es el de las corridas")
        if canonical_json_sha256(scenario.model_dump(mode="json")) != base.scenario_sha256:
            problems.append("el escenario dado no es el de las corridas")
    if protocol.protocol_id != stored.label.protocol_id:
        problems.append("el protocolo dado no es el de la etiqueta")

    version = str(identity.get("journal_version", ""))
    if version == JOURNAL_VERSION:
        expected = dict(identity)
        if fingerprints and identity.get("inputs") != fingerprints:
            problems.append("las huellas de la identidad no son las que prueban las corridas")
    else:
        expected = reexpress_identity(identity, fingerprints)
    digest = identity_digest(expected)
    matches = None
    if version == JOURNAL_VERSION:
        matches = (
            stored.label.search_run_id == f"search-{digest}"
            and stored.label.label_id == f"label-{digest}"
        )
        if not matches:
            problems.append("los identificadores de la etiqueta no salen de su identidad")
    return EvidenceReport(
        label_id=stored.label.label_id,
        search_run_id=stored.label.search_run_id,
        identity_version=version,
        runs=runs,
        input_folders=len(manifests),
        sumo_version=sumo,
        fingerprints=fingerprints,
        expected_identity=expected,
        expected_search_run_id=f"search-{digest}",
        expected_label_id=f"label-{digest}",
        stored_ids_match=matches,
        recomputed=recomputed,
        problems=tuple(dict.fromkeys(problems)),
    )
