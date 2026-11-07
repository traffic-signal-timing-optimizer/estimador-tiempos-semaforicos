"""«bd cargar»: recorre ``datos/`` y carga cada unidad, todo o nada (DEV31 F3; sección 5.7 de F0).

Orden: caso → protocolos → conjuntos de escenarios con su partición → escenarios escritos a mano
→ corridas (con sus métricas) → búsquedas y etiquetas → comparadores → hitos. Cada unidad:

- **ya cargada** (todo igual que en la base): se salta;
- **pendiente**: le falta otra que se publica aparte (su escenario, sus métricas…); no se escribe
  nada y se dice qué falta;
- **rechazada**: una clave ya está con otro contenido, un archivo cambió después de cargarse o la
  base la rechaza por una regla (por ejemplo, un escenario preliminar asignado a prueba). Queda en
  ``control.conflictos``;
- **no cargable**: la carpeta no tiene un formato que se pueda cargar (por ejemplo, las corridas
  de DEV00 sin escenario). Su archivo queda registrado con su motivo.

La carga se registra en ``control.cargas`` al empezar y se cierra al terminar con sus conteos y
la huella de contenido de la base (QA36). Solo puede haber una carga a la vez.
"""

import importlib.metadata
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from semaforo.aprendizaje.split_store import StoredSplit, read_split
from semaforo.bd.candado import try_exclusive
from semaforo.bd.carga.caso import (
    case_unit,
    protocol_unit,
    scenario_set_unit,
    scenario_unit,
)
from semaforo.bd.carga.corridas import PROGRAMS, SearchRun, run_unit
from semaforo.bd.carga.decisiones import Decision, DecisionIndex, apply_decision, decision_unit
from semaforo.bd.carga.fuentes import Source, Sources, children, discover, relative
from semaforo.bd.carga.hitos import milestone_unit
from semaforo.bd.carga.insercion import Catalog, KeyConflict, write_rows
from semaforo.bd.carga.modelo import (
    DATA_ROOT,
    CargaError,
    Pending,
    Row,
    Unit,
    artifact_id,
    read_file,
)
from semaforo.bd.carga.referencias import (
    Trace,
    comparators_unit,
    read_trace,
    search_unit,
    trace_runs,
)
from semaforo.bd.conexion import CARGA, BdError, Connection, connect
from semaforo.bd.esquema import installed_version, schema_version
from semaforo.bd.verificacion import content_hash
from semaforo.datos.scenario_set import read_scenario_set
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.case import Case
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.simulacion.environment import capture_environment
from semaforo.trazabilidad.hashing import sha256_file
from semaforo.trazabilidad.store import utc_now

__all__ = ["LoadOptions", "LoadReport", "UnitOutcome", "artifact_rows", "load_workspace"]

CONFLICT_TABLES = {"control.artefactos": "hash_mismatch"}
PRELIMINARY_TO_TEST = "SM003"

Status = Literal["loaded", "already", "pending", "rejected", "not_loadable", "excluded"]


class UnitOutcome(FrozenModel):
    """Qué pasó con una unidad."""

    key: str
    kind: str
    status: Status
    detail: str | None
    rows: dict[str, int]


class LoadReport(FrozenModel):
    """Informe de una carga (no incluye rutas de la máquina)."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    carga_id: str
    status: Literal["completed", "interrupted"]
    started_at: datetime
    finished_at: datetime
    schema_version_db: str
    counts: dict[str, int]
    rows_by_table: dict[str, int]
    content_sha256: str | None
    units: list[UnitOutcome]
    notes: list[str]


@dataclass(frozen=True)
class LoadOptions:
    """Qué autoriza la carga.

    - ``preliminary``: cargar escenarios sin partición congelada, marcados como preliminares (no
      podrán pasar después a prueba);
    - ``loose_runs``: cargar como diagnóstico las corridas que ninguna búsqueda publicada usa;
    - ``without_metrics``: cargar las corridas exitosas que no tienen métricas publicadas, con sus
      columnas de métricas vacías (por ejemplo, porque su FCD no cubre la zona del protocolo).
      Después ya no se les pueden agregar: es una decisión explícita;
    - ``kinds``: solo esas clases de unidad (por ejemplo, ``{"milestone"}``); ``None`` es todo;
    - ``repository``: la carpeta del repositorio, para las actas de los hitos;
    - ``content``: calcular la huella de contenido al cerrar la carga.
    """

    preliminary: bool = False
    loose_runs: bool = False
    without_metrics: bool = False
    kinds: frozenset[str] | None = None
    repository: Path | None = None
    content: bool = True


# Unidades que, una vez cargadas, no pueden cambiar: si su archivo principal ya está en la base
# con la misma huella, se saltan sin volver a leer la carpeta. Un conjunto de escenarios no entra:
# su partición puede publicarse después.
FAST_SKIP = frozenset(
    {"protocol", "scenario", "run", "search", "comparators", "milestone", "decision"}
)


@dataclass
class _Tally:
    outcomes: list[UnitOutcome] = field(default_factory=list[UnitOutcome])
    rows: dict[str, int] = field(default_factory=dict[str, int])
    files_read: int = 0
    files_loaded: int = 0
    files_rejected: int = 0
    notes: dict[str, int] = field(default_factory=dict[str, int])

    def add(self, outcome: UnitOutcome) -> None:
        self.outcomes.append(outcome)
        for table, count in outcome.rows.items():
            self.rows[table] = self.rows.get(table, 0) + count

    def note(self, text: str) -> None:
        self.notes[text] = self.notes.get(text, 0) + 1

    def note_lines(self) -> list[str]:
        return [
            text if count == 1 else f"{text} (en {count} unidades)"
            for text, count in self.notes.items()
        ]


# --- descubrimiento --------------------------------------------------------------------------
# El recorrido de ``datos/`` vive en ``fuentes`` (catálogo único, C1.1).


class _Programs:
    """Busca un programa derivado por la huella de su manifiesto (con memoria por caso)."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.index: dict[str, dict[str, str]] = {}

    def __call__(self, case_id: str, manifest_sha: str) -> str | None:
        if case_id not in self.index:
            found: dict[str, str] = {}
            for folder in children(self.workspace / PROGRAMS / case_id):
                manifest = folder / "manifiesto.json"
                if manifest.is_file() and not manifest.is_symlink():
                    found[sha256_file(manifest)] = relative(self.workspace, folder)
            self.index[case_id] = found
        return self.index[case_id].get(manifest_sha)


# --- escritura -------------------------------------------------------------------------------


def artifact_rows(unit: Unit, *, status: str = "intact", reason: str | None = None) -> list[Row]:
    moment = utc_now()
    rows: dict[str, Row] = {}
    for record in unit.files:
        rows[record.artifact_id] = {
            "artefacto_id": record.artifact_id,
            "raiz": record.root,
            "ruta_relativa": record.relative,
            "tipo": record.kind,
            "tamano_bytes": record.size,
            "sha256": record.sha256,
            "manifiesto_id": record.manifest,
            "estado": status,
            "motivo": reason,
            "registrado_en": moment,
        }
    return list(rows.values())


def _missing(connection: Connection, catalog: Catalog, unit: Unit) -> str | None:
    """El primer requisito de la unidad que no está en la base, o ``None``."""
    for need in unit.needs:
        info = catalog.tables[need.table]
        condition = sql.SQL(" AND ").join(
            sql.SQL("{} = %s").format(sql.Identifier(column)) for column in need.key
        )
        query = sql.SQL("SELECT 1 FROM {} WHERE {} LIMIT 1").format(info.identifier, condition)
        if connection.execute(query, list(need.key.values())).fetchone() is None:
            return need.reason
    return None


def _record_conflict(  # noqa: PLR0913  (cada dato del conflicto es de solo palabra clave)
    connection: Connection,
    carga_id: str,
    *,
    kind: str,
    detail: str,
    table: str | None = None,
    key: str | None = None,
    loaded_sha: str | None = None,
    new_sha: str | None = None,
    artifact_id: str,
    decided: Decision | None = None,
) -> None:
    """Agrega un conflicto, salvo que el mismo ya esté registrado (cargar dos veces no duplica).

    El mismo conflicto es el de igual tipo, tabla, clave, huella nueva y archivo, **haya sido
    decidido o no**: un conflicto ya decidido no vuelve a abrirse en la carga siguiente. Si hay una
    decisión publicada para ese archivo y esa huella, el conflicto nace ya decidido.
    """
    with connection.transaction():
        exists = connection.execute(
            "SELECT 1 FROM control.conflictos WHERE tipo = %s AND tabla_destino IS NOT DISTINCT "
            "FROM %s AND clave IS NOT DISTINCT FROM %s AND huella_nueva IS NOT DISTINCT FROM %s "
            "AND artefacto_id = %s",
            (kind, table, key, new_sha, artifact_id),
        ).fetchone()
        if exists is not None:
            return
        connection.execute(
            "INSERT INTO control.conflictos (conflicto_id, tipo, tabla_destino, clave, "
            "huella_cargada, huella_nueva, detalle, detectado_en, decision, decidido_en, "
            "decidido_por, carga_id, artefacto_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                f"conflicto-{utc_now():%Y%m%dT%H%M%SZ}-{secrets.token_hex(4)}",
                kind,
                table,
                key,
                loaded_sha,
                new_sha,
                detail,
                utc_now(),
                None if decided is None else decided.decision,
                None if decided is None else decided.decidido_en,
                None if decided is None else decided.responsable,
                carga_id,
                artifact_id,
            ),
        )


def _known_sha(connection: Connection, artifact_id: str) -> str | None:
    row = connection.execute(
        "SELECT sha256 FROM control.artefactos WHERE artefacto_id = %s", (artifact_id,)
    ).fetchone()
    return None if row is None else str(row[0])


def _conflicts(connection: Connection, carga_id: str, unit: Unit, found: list[KeyConflict]) -> str:
    """Registra los conflictos de una unidad y devuelve el resumen."""
    main = unit.files[0].artifact_id
    by_id = {record.artifact_id: record for record in unit.files}
    for conflict in found:
        if conflict.table == "control.artefactos":
            record = by_id.get(conflict.key)
            artifact = conflict.key if conflict.key in by_id else main
            loaded = _known_sha(connection, artifact)
            _record_conflict(
                connection,
                carga_id,
                kind="hash_mismatch",
                detail=f"el archivo cambió después de cargarse: {conflict.key}",
                table=conflict.table,
                key=conflict.key,
                loaded_sha=loaded,
                new_sha=None if record is None else record.sha256,
                artifact_id=artifact,
            )
        else:
            _record_conflict(
                connection,
                carga_id,
                kind="key_conflict",
                detail=f"la clave {conflict.key} ya está en {conflict.table} con otro contenido",
                table=conflict.table,
                key=conflict.key,
                new_sha=unit.files[0].sha256,
                artifact_id=main,
            )
    first = found[0]
    return f"{len(found)} conflictos; el primero en {first.table}: {first.key}"


def _write(
    connection: Connection, catalog: Catalog, carga_id: str, unit: Unit
) -> tuple[Status, str | None, dict[str, int]]:
    rows = {"control.artefactos": artifact_rows(unit), **unit.rows}
    try:
        with connection.transaction():
            result = write_rows(connection, catalog, rows, carga_id)
            if result.conflicts:
                raise _Rollback(result.conflicts)
    except _Rollback as rollback:
        return "rejected", _conflicts(connection, carga_id, unit, rollback.conflicts), {}
    except psycopg.Error as error:
        detail = _database_reason(error)
        kind = (
            "preliminary_now_test"
            if getattr(error, "sqlstate", None) == PRELIMINARY_TO_TEST
            else "key_conflict"
        )
        _record_conflict(
            connection,
            carga_id,
            kind=kind,
            detail=detail,
            new_sha=unit.files[0].sha256,
            artifact_id=_registered(connection, catalog, carga_id, unit),
        )
        return "rejected", detail, {}
    new = {table: count for table, count in result.new.items() if count}
    if not new:
        return "already", None, {}
    return "loaded", None, new


class _Rollback(Exception):
    """No es un error: deshace la transacción de una unidad con conflictos, a propósito."""

    def __init__(self, conflicts: list[KeyConflict]) -> None:
        super().__init__("conflictos")
        self.conflicts = conflicts


def _database_reason(error: psycopg.Error) -> str:
    diagnostic = getattr(error, "diag", None)
    primary = None if diagnostic is None else getattr(diagnostic, "message_primary", None)
    text = primary or str(error).strip().splitlines()[0]
    return f"la base rechazó la unidad: {text}"


def _registered(connection: Connection, catalog: Catalog, carga_id: str, unit: Unit) -> str:
    """El artefacto principal de una unidad rechazada, registrado como «rechazado»."""
    main = unit.files[0]
    if _known_sha(connection, main.artifact_id) is None:
        row = artifact_rows(
            Unit(unit.key, unit.kind, [main]), status="rejected", reason="rechazado"
        )
        with connection.transaction():
            write_rows(connection, catalog, {"control.artefactos": row}, carga_id)
    return main.artifact_id


def _not_loadable(  # noqa: PLR0913, PLR0917  (todo describe el archivo no cargable)
    connection: Connection,
    catalog: Catalog,
    carga_id: str,
    workspace: Path,
    relative: str,
    reason: str,
    decisions: DecisionIndex,
) -> Decision | None:
    """Registra el archivo de una carpeta no cargable (una sola vez) y su conflicto.

    Devuelve la decisión publicada que cubre ese archivo con esa huella, si la hay: el conflicto
    nace ya decidido y la unidad queda «excluida con decisión». Si el archivo ya estaba
    registrado con **otra** huella (cambió después), se registra un conflicto nuevo para la
    versión nueva: la decisión de la versión vieja no la cubre.
    """
    path = workspace / relative
    if not path.is_file():
        return None
    record, _ = read_file(workspace, DATA_ROOT, relative, "manifest")
    covering = decisions.covering(relative, record.sha256)
    unit = Unit(key=relative, kind="not_loadable", files=[record])
    rows = artifact_rows(unit, status="not_loadable", reason=reason)
    with connection.transaction():
        result = write_rows(connection, catalog, {"control.artefactos": rows}, carga_id)
    if result.new.get("control.artefactos"):
        _record_conflict(
            connection,
            carga_id,
            kind="not_loadable",
            detail=reason,
            new_sha=record.sha256,
            artifact_id=record.artifact_id,
            decided=covering,
        )
    elif result.conflicts:
        known = _known_sha(connection, record.artifact_id)
        if known != record.sha256:
            _record_conflict(
                connection,
                carga_id,
                kind="not_loadable",
                detail=f"{reason} (versión nueva del archivo)",
                loaded_sha=known,
                new_sha=record.sha256,
                artifact_id=record.artifact_id,
                decided=covering,
            )
    return covering


@dataclass
class _Run:
    """Lo que necesita cada paso de la carga."""

    connection: Connection
    catalog: Catalog
    carga_id: str
    workspace: Path
    options: LoadOptions
    tally: _Tally
    sources: Sources
    cases: dict[tuple[str, str], Case] = field(default_factory=dict[tuple[str, str], Case])
    decisions: DecisionIndex = field(default_factory=lambda: DecisionIndex({}))

    def wanted(self, kind: str) -> bool:
        return self.options.kinds is None or kind in self.options.kinds

    def _known(self, mains: tuple[str, ...]) -> tuple[Status, str | None, str] | None:
        """Si todos los archivos principales ya están en la base con su huella, el resultado.

        El tercer valor es la huella del primer archivo principal (la de la unidad).
        """
        found: list[tuple[str, str | None, str]] = []
        for relative_path in mains:
            path = self.workspace / relative_path
            if path.is_symlink() or not path.is_file():
                return None
            digest = sha256_file(path)
            row = self.connection.execute(
                "SELECT sha256, estado, motivo FROM control.artefactos WHERE artefacto_id = %s",
                (f"{DATA_ROOT}:{relative_path}",),
            ).fetchone()
            if row is None or row[0] != digest:
                return None
            found.append((str(row[1]), None if row[2] is None else str(row[2]), digest))
        if not found:
            return None
        if all(state == "intact" for state, _, _ in found):
            return "already", None, found[0][2]
        if found[0][0] == "not_loadable":
            return "not_loadable", found[0][1], found[0][2]
        return None

    def _excluded(self, main: str, sha256: str, reason: str | None) -> tuple[Status, str | None]:
        """«No cargable», o «excluida con decisión» si una decisión publicada cubre ese archivo."""
        covering = self.decisions.covering(main, sha256)
        if covering is None:
            return "not_loadable", reason
        return "excluded", f"{reason} · decisión {covering.decision_id}: {covering.decision}"

    def exclude(self, main: str, reason: str) -> tuple[Status, str]:
        """Registra el archivo principal de una unidad no cargable y dice cómo queda."""
        covering = _not_loadable(
            self.connection,
            self.catalog,
            self.carga_id,
            self.workspace,
            main,
            reason,
            self.decisions,
        )
        if covering is None:
            return "not_loadable", reason
        return "excluded", f"{reason} · decisión {covering.decision_id}: {covering.decision}"

    def unit(
        self,
        kind: str,
        key: str,
        main: str,
        build: Callable[[], Unit | None],
        *,
        mains: tuple[str, ...] | None = None,
    ) -> Unit | None:
        """Construye y escribe una unidad; registra su resultado."""
        if kind in FAST_SKIP:
            known = self._known((main,) if mains is None else mains)
            if known is not None:
                status, detail, digest = known
                if status == "not_loadable":
                    status, detail = self._excluded(main, digest, detail)
                self.tally.add(
                    UnitOutcome(key=key, kind=kind, status=status, detail=detail, rows={})
                )
                return None
        try:
            unit = build()
        except Pending as pending:
            self.tally.add(
                UnitOutcome(key=key, kind=kind, status="pending", detail=pending.reason, rows={})
            )
            return None
        except (DomainError, CargaError) as error:
            status, detail = self.exclude(main, f"{error.code.value}: {error.message}")
            self.tally.add(UnitOutcome(key=key, kind=kind, status=status, detail=detail, rows={}))
            return None
        if unit is None:
            return None
        self.tally.files_read += len(unit.files)
        for text in unit.notes:
            self.tally.note(text)
        missing = _missing(self.connection, self.catalog, unit)
        if missing is not None:
            self.tally.add(
                UnitOutcome(key=unit.key, kind=kind, status="pending", detail=missing, rows={})
            )
            return None
        status, detail, rows = _write(self.connection, self.catalog, self.carga_id, unit)
        if status == "loaded":
            self.tally.files_loaded += rows.get("control.artefactos", 0)
        if status == "rejected":
            self.tally.files_rejected += len(unit.files)
        self.tally.add(
            UnitOutcome(key=unit.key, kind=kind, status=status, detail=detail, rows=rows)
        )
        return unit


# --- los pasos -------------------------------------------------------------------------------


def _cases(run: _Run) -> None:
    for source in run.sources.of("case"):
        found: dict[str, Case] = {}

        def build(name: str = source.name, keep: dict[str, Case] = found) -> Unit:
            unit, case = case_unit(run.workspace, name)
            keep["case"] = case
            return unit

        unit = run.unit("case", source.key, source.main, build)
        case = found.get("case")
        if case is not None and unit is not None and _loaded_or_same(run, unit.key):
            run.cases[(case.case_id, case.case_version)] = case


def _loaded_or_same(run: _Run, key: str) -> bool:
    last = next((o for o in reversed(run.tally.outcomes) if o.key == key), None)
    return last is not None and last.status in ("loaded", "already")


def _protocols(run: _Run) -> None:
    for source in run.sources.of("protocol"):
        run.unit(
            "protocol",
            source.key,
            source.main,
            lambda r=source.main: protocol_unit(run.workspace, r)[0],
        )


def _splits(run: _Run) -> dict[str, tuple[str, StoredSplit]]:
    """Particiones publicadas por la huella de contenido de su conjunto de escenarios."""
    found: dict[str, tuple[str, StoredSplit]] = {}
    for folder in (source.folder for source in run.sources.of("split")):
        try:
            stored = read_split(run.workspace / folder)
        except DomainError as error:
            status, detail = run.exclude(
                f"{folder}/manifiesto.json", f"{error.code.value}: {error.message}"
            )
            run.tally.add(
                UnitOutcome(
                    key=f"particion:{folder}", kind="split", status=status, detail=detail, rows={}
                )
            )
            continue
        found[stored.manifest.scenario_set_content_id] = (folder, stored)
    return found


def _scenario_sets(run: _Run) -> None:
    splits = _splits(run)
    for source in run.sources.of("scenario_set"):

        def build(folder: str = source.folder) -> Unit:
            scenario_set = read_scenario_set(run.workspace / folder)
            manifest = scenario_set.manifest
            case = run.cases.get((manifest.case_id, manifest.case_version))
            if case is None:
                raise Pending(f"falta el caso {manifest.case_id} {manifest.case_version}")
            split = splits.get(manifest.content_id)
            if split is None and not run.options.preliminary:
                raise Pending(
                    "el conjunto no tiene partición congelada: solo se carga como preliminar "
                    "(--preliminar)"
                )
            return scenario_set_unit(
                run.workspace,
                folder,
                scenario_set,
                case,
                split,
                preliminary=run.options.preliminary,
            )

        run.unit("scenario_set", source.key, source.main, build)


def _hand_scenarios(run: _Run) -> None:
    for source in run.sources.of("scenario"):

        def build(relative: str = source.main) -> Unit | None:
            built = scenario_unit(run.workspace, relative, run.cases)
            if built is None:
                return None
            if not run.options.preliminary:
                raise Pending(
                    "un escenario escrito a mano no tiene partición: solo se carga como "
                    "preliminar (--preliminar)"
                )
            return built[0]

        run.unit("scenario", source.key, source.main, build)


def _traces(run: _Run) -> tuple[list[Trace], dict[str, SearchRun]]:
    traces: list[Trace] = []
    runs: dict[str, SearchRun] = {}
    for folder in (source.folder for source in run.sources.of("search")):
        try:
            trace = read_trace(run.workspace, folder)
            found = trace_runs(trace)
        except DomainError as error:
            status, detail = run.exclude(
                f"{folder}/manifiesto.json", f"{error.code.value}: {error.message}"
            )
            run.tally.add(
                UnitOutcome(
                    key=f"busqueda:{folder}", kind="search", status=status, detail=detail, rows={}
                )
            )
            continue
        repeated = sorted(set(found) & set(runs))
        if repeated:
            run.tally.note(f"{folder}: corridas que ya usa otra búsqueda ({repeated[0]}…)")
            continue
        traces.append(trace)
        runs.update(found)
    return traces, runs


def _runs(run: _Run, searches: dict[str, SearchRun]) -> None:
    programs = _Programs(run.workspace)
    for source in run.sources.of("run"):
        run.unit(
            "run",
            source.key,
            source.main,
            lambda r=source.name: run_unit(
                run.workspace,
                r,
                run.cases,
                searches,
                programs,
                diagnostics=run.options.loose_runs,
                require_metrics=not run.options.without_metrics,
            ),
            mains=source.mains,
        )


def _searches(run: _Run, traces: list[Trace]) -> None:
    for trace in traces:
        run.unit(
            "search",
            f"busqueda:{trace.folder}",
            f"{trace.folder}/manifiesto.json",
            lambda t=trace: search_unit(t, run.cases),
        )


def _comparators(run: _Run) -> None:
    for source in run.sources.of("comparators"):
        run.unit(
            "comparators",
            source.key,
            source.main,
            lambda f=source.folder: comparators_unit(run.workspace, f, run.cases),
        )


def _milestones(run: _Run) -> None:
    for source in run.sources.of("milestone"):
        run.unit(
            "milestone",
            source.key,
            source.main,
            lambda r=source.folder: milestone_unit(run.workspace, run.options.repository, r),
        )


@dataclass(frozen=True)
class _ReadDecision:
    source: Source
    decision: Decision
    unit: Unit


def _decisions_read(
    run: _Run,
) -> tuple[list[_ReadDecision], dict[str, tuple[ErrorCode, str]]]:
    """Lee las decisiones publicadas y arma el índice de las válidas (``run.decisions``).

    De dos decisiones sobre la misma ruta y la misma huella vale la primera (por nombre de
    carpeta); la otra se rechaza. Se leen siempre, aunque la carga sea de otra clase, porque
    deciden cómo queda cada archivo excluido.
    """
    valid: list[_ReadDecision] = []
    invalid: dict[str, tuple[ErrorCode, str]] = {}
    by_file: dict[tuple[str, str], Decision] = {}
    for source in run.sources.of("decision"):
        try:
            decision, unit = decision_unit(run.workspace, run.options.repository, source.folder)
        except (DomainError, CargaError) as error:
            invalid[source.key] = (error.code, error.message)
            continue
        identity = (artifact_id(DATA_ROOT, decision.ruta), decision.huella)
        first = by_file.get(identity)
        if first is not None:
            invalid[source.key] = (
                ErrorCode.INPUT_SCHEMA,
                f"ya hay una decisión de esa ruta y esa huella ({first.decision_id})",
            )
            continue
        by_file[identity] = decision
        valid.append(_ReadDecision(source, decision, unit))
    run.decisions = DecisionIndex(by_file)
    return valid, invalid


def _refuse(code: ErrorCode, message: str) -> Unit:
    raise CargaError(code, message)


def _decisions_apply(
    run: _Run, valid: list[_ReadDecision], invalid: dict[str, tuple[ErrorCode, str]]
) -> None:
    """Registra las decisiones como unidades y aplica cada una a su conflicto pendiente."""
    ready = {entry.source.key: entry for entry in valid}
    for source in run.sources.of("decision"):
        refused = invalid.get(source.key)
        if refused is not None:
            run.unit(
                "decision",
                source.key,
                source.main,
                lambda r=refused: _refuse(r[0], r[1]),
            )
            continue
        entry = ready[source.key]
        run.unit("decision", source.key, source.main, lambda u=entry.unit: u)
        applied = apply_decision(run.connection, entry.decision)
        if applied:
            run.tally.note(
                f"decisión {entry.decision.decision_id}: aplicada a {applied} conflicto(s) de "
                f"{entry.decision.ruta}"
            )


def _steps(run: _Run) -> None:
    decisions, refused = _decisions_read(run)
    _cases(run)
    if run.wanted("protocol"):
        _protocols(run)
    if run.wanted("scenario_set"):
        _scenario_sets(run)
    if run.wanted("scenario"):
        _hand_scenarios(run)
    traces, searches = _traces(run) if run.wanted("run") or run.wanted("search") else ([], {})
    if run.wanted("run"):
        _runs(run, searches)
    if run.wanted("search"):
        _searches(run, traces)
    if run.wanted("comparators"):
        _comparators(run)
    if run.wanted("milestone"):
        _milestones(run)
    if run.wanted("decision"):
        _decisions_apply(run, decisions, refused)


# --- la carga --------------------------------------------------------------------------------


def _start(connection: Connection, options: LoadOptions, carga_id: str, started: datetime) -> str:
    environment = capture_environment()
    commit = environment.get("commit")
    modified = environment.get("code_modified")
    version = installed_version(connection)
    if version != schema_version():
        raise BdError(
            ErrorCode.INPUT_SCHEMA,
            f"la base tiene el esquema {version} y el código espera {schema_version()}: "
            "cree una base nueva y vuelva a cargar",
            "schema",
        )
    server = connection.execute("SHOW server_version").fetchone()
    command = {
        "preliminar": options.preliminary,
        "sueltas": options.loose_runs,
        "sin_metricas": options.without_metrics,
        "clases": None if options.kinds is None else sorted(options.kinds),
    }
    with connection.transaction():
        connection.execute(
            "INSERT INTO control.cargas (carga_id, inicio, estado, comando, version_paquete, "
            "commit_codigo, arbol_limpio, version_postgres, version_esquema) "
            "VALUES (%s, %s, 'running', %s, %s, %s, %s, %s, %s)",
            (
                carga_id,
                started,
                Jsonb(command),
                importlib.metadata.version("semaforo"),
                commit,
                None if modified is None else modified == "false",
                None if server is None else str(server[0]),
                version,
            ),
        )
    return schema_version()


def _finish(  # noqa: PLR0913  (cada dato del cierre es de solo palabra clave)
    connection: Connection,
    carga_id: str,
    *,
    status: str,
    tally: _Tally,
    content: str | None,
    finished: datetime,
) -> None:
    with connection.transaction():
        connection.execute(
            "UPDATE control.cargas SET estado = %s, fin = %s, artefactos_leidos = %s, "
            "artefactos_cargados = %s, artefactos_rechazados = %s, filas_por_tabla = %s, "
            "huella_contenido = %s WHERE carga_id = %s",
            (
                status,
                finished,
                tally.files_read,
                tally.files_loaded,
                tally.files_rejected,
                Jsonb(tally.rows),
                content,
                carga_id,
            ),
        )


def load_workspace(
    workspace: Path,
    options: LoadOptions | None = None,
    *,
    database: str | None = None,
    connector: Callable[..., Connection] = connect,
) -> LoadReport:
    """Carga ``workspace`` (la carpeta ``datos/``) en la base, como ``semaforo_carga``.

    Raises:
        BdError: DEPENDENCY_MISSING si no hay conexión; INPUT_SCHEMA si la base no tiene el
            esquema que espera este código o ya hay otra carga en curso.
    """
    chosen = options or LoadOptions()
    # Sin transacción implícita: cada unidad abre y cierra la suya (todo o nada).
    with connector(CARGA, database=database, autocommit=True) as connection:
        if not try_exclusive(connection):
            raise BdError(
                ErrorCode.INPUT_SCHEMA,
                "ya hay otra carga o una verificación en curso (candado ocupado)",
                "carga",
            )
        catalog = Catalog.load(connection)
        started = utc_now()
        carga_id = f"{started:%Y%m%dT%H%M%SZ}_{secrets.token_hex(4)}"
        version = _start(connection, chosen, carga_id, started)
        tally = _Tally()
        run = _Run(connection, catalog, carga_id, workspace, chosen, tally, discover(workspace))
        status: Literal["completed", "interrupted"] = "interrupted"
        content: str | None = None
        try:
            _steps(run)
            status = "completed"
        finally:
            if status == "completed" and chosen.content:
                content, _ = content_hash(connection, catalog)
            _finish(
                connection,
                carga_id,
                status=status,
                tally=tally,
                content=content,
                finished=utc_now(),
            )
        counts = {
            name: sum(1 for o in tally.outcomes if o.status == name)
            for name in ("loaded", "already", "pending", "rejected", "not_loadable", "excluded")
        }
        return LoadReport(
            carga_id=carga_id,
            status=status,
            started_at=started,
            finished_at=utc_now(),
            schema_version_db=version,
            counts=counts,
            rows_by_table=dict(sorted(tally.rows.items())),
            content_sha256=content,
            units=tally.outcomes,
            notes=tally.note_lines(),
        )
