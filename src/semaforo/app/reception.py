"""Servicio de recepción de una simulación SUMO (F7 y F8 de DEV00, ADR09).

Encadena las piezas de DEV00 dentro de un espacio de trabajo (``datos/``):

1. copia inmutable de las entradas (F2), en ``originales/sumo/<snapshot_id>/``;
2. auditoría de rutas, demanda y comportamiento (F4), inventario de la red (F3) y tabla de
   movimientos por carril (F8) sobre esa copia;
3. corrida base de SUMO (F6), en ``ejecuciones/<run_id>/``;
4. registro de la recepción, en ``derivados/recepcion/<reception_id>/``, publicado de una vez y
   nunca sobrescrito: los artefactos anteriores, las planillas de revisión QA23 y QA24, el detalle
   privado de los hallazgos y el informe público (F8).

El registro guarda la huella SHA-256 del manifiesto de la corrida base, para acreditar después
que la corrida no se rehízo (ADR03: un hash guardado junto a un archivo modificable no basta), y
lista las ejecuciones incompletas que dejó una caída anterior. ``publish_public_report`` copia el
informe público a ``docs/recepcion/`` tras verificar la recepción.
"""

import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ValidationError

from semaforo.app.reception_models import (
    BaseRunRecord,
    IncompleteRun,
    ProposedStatus,
    ReceptionRecord,
)
from semaforo.app.reception_report import (
    find_machine_paths,
    findings_markdown,
    public_report,
    qa23_csv,
    qa24_csv,
)
from semaforo.caso.audit import DEFAULT_CLASS, audit_simulation
from semaforo.caso.inventory import read_network_inventory
from semaforo.caso.movements import MovementTable, read_movements
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
    "publish_public_report",
    "read_reception",
    "receive_case",
]

SNAPSHOTS = "originales/sumo"
RUNS = "ejecuciones"
RECEPTIONS = "derivados/recepcion"
RECORD = "reception.json"
PUBLIC_REPORT = "informe_publico.md"
RECEPTION_ID_PATTERN = re.compile(r"\d{8}T\d{6}Z_[a-f0-9]{8}")
MAX_RECORD_BYTES = 16 * 1024 * 1024
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


def exit_code_for(code: ErrorCode | str) -> int:
    """Código de salida de la CLI para un código de error; 1 si no se reconoce."""
    try:
        return EXIT_CODES[ErrorCode(code)]
    except (ValueError, KeyError):
        return INTERNAL_ERROR_EXIT


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
    classes = sorted({item.vclass for item in audit.demand}) or [DEFAULT_CLASS]
    net = None if audit.net_file is None else snapshot.path / audit.net_file
    inventory = None if net is None else read_network_inventory(net)
    movements = None if net is None else read_movements(net, classes)
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
    run, summary = result.manifest, result.summary
    files: dict[str, bytes] = {
        "snapshot_manifest.json": _json(manifest),
        "audit.json": _json(audit),
    }
    if inventory is not None and movements is not None:
        files["inventory.json"] = _json(inventory)
        files["movements.json"] = _json(MovementTable(classes=classes, movements=movements))
        files["revision_qa23.csv"] = qa23_csv(movements)
        files["revision_qa24.csv"] = qa24_csv(inventory, movements, audit)
    files["hallazgos.md"] = findings_markdown(
        reception_id=reception_id,
        inventory=inventory,
        movements=movements,
        audit=audit,
        summary=summary,
        incomplete_runs=incomplete,
    ).encode("utf-8")
    counts = {
        "inventory": 0 if inventory is None else len(inventory.findings),
        "audit": len(audit.findings),
        "run": 0 if summary is None else len(summary.findings),
    }
    status: ProposedStatus
    if run.status != "succeeded":
        status = "failed"
    else:
        status = "with_findings" if any(counts.values()) else "acceptable"
    base_run = _base_run(run, runs_root, summary)
    sumo_version = run.environment.get("sumo")
    files[PUBLIC_REPORT] = public_report(
        reception_id=reception_id,
        created_at=created_at,
        sumo_version=sumo_version,
        proposed_status=status,
        snapshot=manifest,
        run=base_run,
        artifacts=_artifacts(files),
    ).encode("utf-8")
    record = ReceptionRecord(
        reception_id=reception_id,
        created_at=created_at,
        source_name=source.name,
        entry_config=entry,
        case_id=case_id,
        snapshot_id=manifest.snapshot_id,
        snapshot_path=f"{SNAPSHOTS}/{manifest.snapshot_id}",
        snapshot_reused=snapshot.reused,
        sumo_version=sumo_version,
        artifacts=_artifacts(files),
        base_run=base_run,
        finding_counts=counts,
        proposed_status=status,
        exit_code=_exit_code(run),
        incomplete_runs=incomplete,
    )
    files[RECORD] = _json(record)
    try:
        publish_files(final, files)
    except FileExistsError as error:
        raise DomainError(
            ErrorCode.RUN_EXISTS, "la recepción ya existe y no se sobrescribe", "reception_id"
        ) from error
    return record


def read_reception(workspace: Path, reception_id: str) -> ReceptionRecord:
    """Lee una recepción publicada y comprueba que su carpeta coincide con su registro.

    Raises:
        DomainError: PATH_NOT_ALLOWED si el identificador no es válido; INPUT_SCHEMA si la
            recepción no existe o su registro no es válido; HASH_MISMATCH si un artefacto falta,
            sobra o fue modificado.
    """
    folder = reception_folder(workspace, reception_id)
    path = folder / RECORD
    if not path.is_file():
        raise DomainError(ErrorCode.INPUT_SCHEMA, "la recepción no existe", "reception_id")
    try:
        if path.stat().st_size > MAX_RECORD_BYTES:
            raise DomainError(ErrorCode.INPUT_SCHEMA, "el registro es demasiado grande", RECORD)
        record = ReceptionRecord.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as error:
        raise DomainError(
            ErrorCode.INPUT_SCHEMA,
            f"registro ilegible o no válido ({type(error).__name__})",
            RECORD,
        ) from error
    if record.reception_id != reception_id:
        raise DomainError(ErrorCode.HASH_MISMATCH, "el registro es de otra recepción", RECORD)
    present = {p.name for p in folder.iterdir()}
    if present != {artifact.path for artifact in record.artifacts} | {RECORD}:
        raise DomainError(
            ErrorCode.HASH_MISMATCH,
            "la carpeta no tiene exactamente los artefactos del registro",
            reception_id,
        )
    for artifact in record.artifacts:
        if sha256_file(folder / artifact.path) != artifact.sha256:
            raise DomainError(
                ErrorCode.HASH_MISMATCH,
                "un artefacto de la recepción fue modificado",
                artifact.path,
            )
    return record


def reception_folder(workspace: Path, reception_id: str) -> Path:
    """Carpeta de una recepción; PATH_NOT_ALLOWED si el identificador no tiene el formato."""
    if not RECEPTION_ID_PATTERN.fullmatch(reception_id):
        raise DomainError(
            ErrorCode.PATH_NOT_ALLOWED,
            f"identificador de recepción no válido: {reception_id!r}",
            "reception_id",
        )
    return workspace / RECEPTIONS / reception_id


def publish_public_report(workspace: Path, reception_id: str, destination: Path) -> Path:
    """Copia el informe público de una recepción verificada a ``destination/<reception_id>.md``.

    Raises:
        DomainError: los de ``read_reception``; PATH_NOT_ALLOWED si el informe contiene rutas de
            un equipo; RUN_EXISTS si el informe ya se publicó (nunca se sobrescribe).
    """
    read_reception(workspace, reception_id)
    text = (reception_folder(workspace, reception_id) / PUBLIC_REPORT).read_text(encoding="utf-8")
    if find_machine_paths(text):
        raise DomainError(
            ErrorCode.PATH_NOT_ALLOWED, "el informe contiene rutas de un equipo", PUBLIC_REPORT
        )
    target = destination / f"{reception_id}.md"
    if target.exists():
        raise DomainError(ErrorCode.RUN_EXISTS, "el informe ya se publicó", target.name)
    destination.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")
    return target


def _json(model: BaseModel) -> bytes:
    return model.model_dump_json(indent=2).encode("utf-8")


def _artifacts(files: Mapping[str, bytes]) -> list[Artifact]:
    return [
        Artifact(artifact_id=name.rsplit(".", 1)[0], path=name, sha256=sha256_bytes(data))
        for name, data in sorted(files.items())
    ]


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
