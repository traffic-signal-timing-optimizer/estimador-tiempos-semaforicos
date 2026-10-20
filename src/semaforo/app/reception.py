"""Servicio de recepción de una simulación SUMO (F7 de DEV00, ADR09).

Encadena las piezas de DEV00 dentro de un espacio de trabajo (``datos/``):

1. copia inmutable de las entradas (F2), en ``originales/sumo/<snapshot_id>/``;
2. auditoría de rutas, demanda y comportamiento (F4) e inventario de la red (F3) sobre esa copia;
3. corrida base de SUMO (F6), en ``ejecuciones/<run_id>/``;
4. registro de la recepción, en ``derivados/recepcion/<reception_id>/``, publicado de una vez y
   nunca sobrescrito.

El registro guarda la huella SHA-256 del manifiesto de la corrida base, para acreditar después
que la corrida no se rehízo (ADR03: un hash guardado junto a un archivo modificable no basta), y
lista las ejecuciones incompletas que dejó una caída anterior.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from semaforo.caso.audit import audit_simulation
from semaforo.caso.base_model import FrozenModel
from semaforo.caso.inventory import read_network_inventory
from semaforo.caso.reception import snapshot_source
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.simulacion.runner import RunLimits, run_simulation
from semaforo.simulacion.summary import Mode, SimulationSummary
from semaforo.trazabilidad.fs import publish_files
from semaforo.trazabilidad.hashing import sha256_bytes, sha256_file
from semaforo.trazabilidad.manifest import Artifact, RunManifest
from semaforo.trazabilidad.store import MANIFEST, TEMP_PREFIX, RunSpec, utc_now

__all__ = [
    "DomainError",
    "IncompleteRun",
    "ReceptionRecord",
    "exit_code_for",
    "receive_case",
]

SNAPSHOTS = "originales/sumo"
RUNS = "ejecuciones"
RECEPTIONS = "derivados/recepcion"
SHA256_PATTERN = r"^[a-f0-9]{64}$"
INTERNAL_ERROR_EXIT = 1
# Diseño técnico, «Errores y códigos de salida».
EXIT_CODES: dict[ErrorCode, int] = {
    ErrorCode.INPUT_SCHEMA: 2,
    ErrorCode.DEPENDENCY_MISSING: 3,
    ErrorCode.SIM_FAILED: 4,
    ErrorCode.SIM_TIMEOUT: 4,
    ErrorCode.OUTPUT_INVALID: 4,
    ErrorCode.HASH_MISMATCH: 5,
    ErrorCode.PATH_NOT_ALLOWED: 5,
    ErrorCode.RUN_EXISTS: 5,
}
ProposedStatus = Literal["acceptable", "with_findings", "failed"]


def exit_code_for(code: ErrorCode | str) -> int:
    """Código de salida de la CLI para un código de error; 1 si no se reconoce."""
    try:
        return EXIT_CODES[ErrorCode(code)]
    except (ValueError, KeyError):
        return INTERNAL_ERROR_EXIT


class BaseRunRecord(FrozenModel):
    """La corrida base de la recepción, enlazada por la huella de su manifiesto."""

    run_id: str
    path: str
    status: str
    manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    exit_code: int | None
    error_code: str | None
    summary: SimulationSummary | None


class IncompleteRun(FrozenModel):
    """Una ejecución que quedó sin publicar (carpeta ``.tmp-``), por ejemplo tras una caída."""

    folder: str
    run_id: str | None
    created_at: datetime | None


class ReceptionRecord(FrozenModel):
    """Registro de una recepción: qué se recibió, qué se produjo y en qué estado quedó.

    Las rutas son relativas al espacio de trabajo. ``proposed_status`` es una propuesta: la valida
    el Product Owner (QA23 y QA24). ``exit_code`` es el código de salida de la CLI.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    reception_id: str
    created_at: datetime
    source_name: str
    entry_config: str
    case_id: str
    snapshot_id: str = Field(pattern=SHA256_PATTERN)
    snapshot_path: str
    snapshot_reused: bool
    sumo_version: str | None
    artifacts: list[Artifact]
    base_run: BaseRunRecord
    finding_counts: dict[str, int]
    proposed_status: ProposedStatus
    exit_code: int
    incomplete_runs: list[IncompleteRun]


def receive_case(  # noqa: PLR0913  (los opcionales son de solo palabra clave)
    source: Path,
    entry_config: str,
    workspace: Path,
    *,
    case_id: str,
    mode: Mode = "base",
    limits: RunLimits | None = None,
    sumo: Path | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> ReceptionRecord:
    """Recibe la simulación de ``source`` y publica su registro.

    Args:
        source: carpeta de la simulación. Solo se lee.
        entry_config: .sumocfg de entrada, relativo a ``source``.
        workspace: espacio de trabajo (``datos/``).
        case_id: identificador del caso en los manifiestos.
        mode: ``base`` o ``smoke`` para la corrida.
        limits: límites de la corrida; si es None, los provisionales.
        sumo: ejecutable de SUMO; si es None, se busca con ``SUMO_HOME``.
        clock: reloj con zona horaria.

    Raises:
        DomainError: si la recepción no puede completarse (origen o .sumocfg no válidos, rutas no
            permitidas, SUMO ausente) o si la recepción ya existe (RUN_EXISTS). Una corrida base
            fallida no es una excepción: queda en el registro con ``proposed_status="failed"``.
    """
    created_at = clock()
    snapshot = snapshot_source(source, entry_config, workspace / SNAPSHOTS)
    manifest = snapshot.manifest
    entry = manifest.entry_config
    audit = audit_simulation(snapshot.path, entry)
    inventory = (
        None if audit.net_file is None else read_network_inventory(snapshot.path / audit.net_file)
    )
    reception_id = f"{created_at.astimezone(UTC):%Y%m%dT%H%M%SZ}_{manifest.snapshot_id[:8]}"
    final = workspace / RECEPTIONS / reception_id
    if final.exists():
        raise DomainError(
            ErrorCode.RUN_EXISTS, "la recepción ya existe y no se sobrescribe", "reception_id"
        )
    runs_root = workspace / RUNS
    incomplete = _incomplete_runs(runs_root)
    spec = RunSpec(
        kind="simulation",
        case_id=case_id,
        case_version=manifest.snapshot_id,
        seed=_seed(audit.config.seed),
    )
    result = run_simulation(
        snapshot.path,
        entry,
        runs_root,
        spec,
        mode=mode,
        limits=limits,
        sumo=sumo,
        declared_vehicles=audit.expected_vehicles_total,
        clock=clock,
    )
    run = result.manifest
    files = {
        "snapshot_manifest.json": manifest.model_dump_json(indent=2).encode("utf-8"),
        "audit.json": audit.model_dump_json(indent=2).encode("utf-8"),
    }
    if inventory is not None:
        files["inventory.json"] = inventory.model_dump_json(indent=2).encode("utf-8")
    counts = {
        "inventory": 0 if inventory is None else len(inventory.findings),
        "audit": len(audit.findings),
        "run": 0 if result.summary is None else len(result.summary.findings),
    }
    failed = run.status != "succeeded"
    record = ReceptionRecord(
        reception_id=reception_id,
        created_at=created_at,
        source_name=source.name,
        entry_config=entry,
        case_id=case_id,
        snapshot_id=manifest.snapshot_id,
        snapshot_path=f"{SNAPSHOTS}/{manifest.snapshot_id}",
        snapshot_reused=snapshot.reused,
        sumo_version=run.environment.get("sumo"),
        artifacts=[
            Artifact(artifact_id=name.removesuffix(".json"), path=name, sha256=sha256_bytes(data))
            for name, data in sorted(files.items())
        ],
        base_run=_base_run(run, runs_root, result.summary),
        finding_counts=counts,
        proposed_status="failed"
        if failed
        else ("with_findings" if any(counts.values()) else "acceptable"),
        exit_code=_exit_code(run),
        incomplete_runs=incomplete,
    )
    files["reception.json"] = record.model_dump_json(indent=2).encode("utf-8")
    try:
        publish_files(final, files)
    except FileExistsError as error:
        raise DomainError(
            ErrorCode.RUN_EXISTS, "la recepción ya existe y no se sobrescribe", "reception_id"
        ) from error
    return record


def _exit_code(run: RunManifest) -> int:
    """0 si la corrida base tuvo éxito; si no, el código de salida de su error."""
    if run.status == "succeeded":
        return 0
    return INTERNAL_ERROR_EXIT if run.error is None else exit_code_for(run.error.code)


def _seed(text: str | None) -> int | None:
    return int(text) if text is not None and text.isdigit() else None


def _base_run(
    run: RunManifest, runs_root: Path, summary: SimulationSummary | None
) -> BaseRunRecord:
    return BaseRunRecord(
        run_id=run.run_id,
        path=f"{RUNS}/{run.run_id}",
        status=run.status,
        manifest_sha256=sha256_file(runs_root / run.run_id / MANIFEST),
        exit_code=run.exit_code,
        error_code=None if run.error is None else run.error.code,
        summary=summary,
    )


def _incomplete_runs(runs_root: Path) -> list[IncompleteRun]:
    """Carpetas ``.tmp-`` de ejecuciones sin publicar y el run_id de su manifiesto provisional."""
    if not runs_root.is_dir():
        return []
    found: list[IncompleteRun] = []
    for folder in sorted(runs_root.iterdir()):
        if not (folder.is_dir() and folder.name.startswith(TEMP_PREFIX)):
            continue
        try:
            provisional = RunManifest.model_validate_json((folder / MANIFEST).read_bytes())
        except (OSError, ValidationError):
            found.append(IncompleteRun(folder=folder.name, run_id=None, created_at=None))
        else:
            found.append(
                IncompleteRun(
                    folder=folder.name, run_id=provisional.run_id, created_at=provisional.created_at
                )
            )
    return found
