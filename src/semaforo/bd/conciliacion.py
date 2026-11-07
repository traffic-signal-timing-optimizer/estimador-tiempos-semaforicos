"""La base coincide con los archivos: cobertura, conteos y demora recalculada (DEV31 F4c; QA33).

``reconcile`` compara la base con los archivos de ``datos/`` por otro camino que el cargador:

0. **Cobertura, en los dos sentidos** (C1.3): parte de lo que **debería** haber (el catálogo de
   ``datos/``, ``fuentes``) y no de lo que la base ya conoce. Cuenta lo cargado, lo excluido con
   decisión, lo excluido pendiente, lo que **falta** en la base y lo que **sobra** en ella. Una base
   vacía da *incompleta*, no *coincide*.
1. **Archivos:** cada archivo íntegro que conoce la base existe, pesa lo mismo y da la misma huella.
2. **Conteos de cada corrida:** vehículos, vehículos de la cohorte y eventos de la base contra las
   líneas de ``cohorte_conciliada.csv`` y de ``sumo.log``; filas de la cola paso a paso contra
   ``metricas.json``; filas por acceso y por movimiento; y la suma de vehículos en cola de la
   ventana de medición.
3. **Demora recalculada:** vuelve a calcular las métricas de cada corrida desde sus archivos con el
   código oficial (``evaluate_run``) y compara **cada columna de métricas** de
   ``resultados_corrida`` con lo que está en la base. Una corrida a la que le falta algo para
   recalcular (su escenario, su protocolo…) queda **no verificada** con su motivo; las demás siguen.

Todo se lee en **una sola instantánea de solo lectura** con el candado compartido
(``instantanea``): si hay una carga en curso, o la última carga cambia mientras se lee, el resultado
es *no concluyente*. No escribe nada. Una diferencia no se corrige aquí: se informa.
"""

import math
from pathlib import Path
from typing import Literal

from semaforo.bd.carga.corridas import METRIC_COLUMNS, log_events, metric_columns
from semaforo.bd.carga.fuentes import Sources, discover
from semaforo.bd.carga.modelo import DATA_ROOT
from semaforo.bd.conexion import CARGA, Connection
from semaforo.bd.instantanea import Inconcluso, lectura_estable
from semaforo.bd.metricas import ProtocolContext, load_context
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.errors import DomainError
from semaforo.evaluacion.published_metrics import METRICS, RUNS, read_run_metrics
from semaforo.evaluacion.run_metrics import evaluate_run
from semaforo.trazabilidad.hashing import sha256_file

__all__ = ["Coverage", "Difference", "ReconcileReport", "reconcile"]

MAX_SHOWN = 200
MAX_KEYS = 50
YES = "sí"
TOLERANCE = 1e-12

Row = dict[str, object]


class Difference(FrozenModel):
    """Una cosa que no coincide: dónde, qué y los dos valores."""

    where: str
    item: str
    database: str
    files: str


class Coverage(FrozenModel):
    """Qué parte de lo publicado en ``datos/`` está en la base, en los dos sentidos."""

    expected: int
    loaded: int
    excluded_with_decision: int
    excluded_pending: int
    missing: int
    surplus: int
    missing_keys: list[str]
    pending_keys: list[str]
    surplus_keys: list[str]


class ReconcileReport(FrozenModel):
    """Resultado de ``bd conciliar`` (sin rutas de la máquina)."""

    schema_version: Literal["1.1.0"] = "1.1.0"
    status: Literal["equal", "different", "incomplete", "inconclusive"]
    reason: str | None
    files_checked: int
    runs_checked: int
    runs_recomputed: int
    runs_unverified: int
    differences_total: int
    differences: list[Difference]
    unverified: list[Difference]
    coverage: Coverage


def _rows(connection: Connection, query: str) -> list[Row]:
    cursor = connection.execute(query.encode())
    names = [column.name for column in cursor.description or []]
    return [dict(zip(names, row, strict=True)) for row in cursor]


def _by_run(connection: Connection, query: str) -> dict[str, int]:
    return {str(row[0]): int(str(row[1])) for row in connection.execute(query.encode())}


def _same(a: object, b: object) -> bool:
    numbers = (int, float)
    if isinstance(a, numbers) and isinstance(b, numbers) and not isinstance(a, bool):
        return math.isclose(float(a), float(b), rel_tol=TOLERANCE, abs_tol=TOLERANCE)
    return a == b


class _Found:
    def __init__(self) -> None:
        self.items: list[Difference] = []
        self.unverified: list[Difference] = []

    def add(self, where: str, item: str, database: object, files: object) -> None:
        self.items.append(
            Difference(where=where, item=item, database=str(database), files=str(files))
        )

    def compare(self, where: str, item: str, database: object, files: object) -> None:
        if not _same(database, files):
            self.add(where, item, database, files)

    def unverify(self, where: str, reason: str) -> None:
        """Una corrida que no se pudo verificar, con su motivo (no es una diferencia)."""
        self.unverified.append(
            Difference(where=where, item="no verificada", database="en la base", files=reason)
        )


def _check_files(
    connection: Connection, workspace: Path, repository: Path | None, found: _Found
) -> int:
    bases = {"datos": workspace, "repositorio": repository}
    checked = 0
    for identifier, root, relative, size, digest in connection.execute(
        b"SELECT artefacto_id, raiz, ruta_relativa, tamano_bytes, sha256 "
        b"FROM control.artefactos WHERE estado = 'intact' ORDER BY artefacto_id"
    ):
        base = bases.get(str(root))
        if base is None:
            continue
        checked += 1
        path = base / str(relative)
        if path.is_symlink() or not path.is_file():
            found.add(str(identifier), "archivo", "está en la base", "no existe")
        elif path.stat().st_size != size:
            found.add(str(identifier), "tamaño", size, path.stat().st_size)
        elif sha256_file(path) != digest:
            found.add(str(identifier), "huella", digest, "otra")
    return checked


def _source_state(
    workspace: Path,
    mains: tuple[str, ...],
    known: dict[str, tuple[str, str]],
    decided: set[tuple[str, str]],
) -> Literal["loaded", "with_decision", "pending", "missing"]:
    """Cómo está en la base una unidad publicada, según sus archivos principales."""
    states: list[str] = []
    for main in mains:
        entry = known.get(f"{DATA_ROOT}:{main}")
        if entry is None:
            return "missing"
        states.append(entry[1])
    if all(state == "intact" for state in states):
        return "loaded"
    path = workspace / mains[0]
    digest = sha256_file(path) if path.is_file() and not path.is_symlink() else None
    if digest is not None and (f"{DATA_ROOT}:{mains[0]}", digest) in decided:
        return "with_decision"
    return "pending"


def _coverage(
    connection: Connection, workspace: Path, sources: Sources, runs: list[Row], found: _Found
) -> Coverage:
    """Lo publicado frente a lo cargado, en los dos sentidos (C1.3)."""
    known = {
        str(identifier): (str(digest), str(state))
        for identifier, digest, state in connection.execute(
            b"SELECT artefacto_id, sha256, estado FROM control.artefactos WHERE raiz = 'datos'"
        )
    }
    decided = {
        (str(identifier), str(digest))
        for identifier, digest in connection.execute(
            b"SELECT artefacto_id, huella_nueva FROM control.conflictos WHERE decision IS NOT NULL"
        )
    }
    buckets: dict[str, list[str]] = {
        "loaded": [],
        "with_decision": [],
        "pending": [],
        "missing": [],
    }
    for source in sources.items:
        if source.kind == "split":
            continue  # las particiones se cargan con su conjunto de escenarios
        state = _source_state(workspace, source.mains, known, decided)
        buckets[state].append(source.key)
    in_database = {f"corrida:{row['run_id']}" for row in runs}
    surplus = sorted(in_database - sources.keys("run"))
    for key in surplus:
        found.add(key, "sobrante", "está en la base", "no está en datos/")
    return Coverage(
        expected=sum(len(keys) for keys in buckets.values()),
        loaded=len(buckets["loaded"]),
        excluded_with_decision=len(buckets["with_decision"]),
        excluded_pending=len(buckets["pending"]),
        missing=len(buckets["missing"]),
        surplus=len(surplus),
        missing_keys=buckets["missing"][:MAX_KEYS],
        pending_keys=buckets["pending"][:MAX_KEYS],
        surplus_keys=surplus[:MAX_KEYS],
    )


def _counts_from_files(workspace: Path, run_id: str) -> tuple[int, int, int] | None:
    """Vehículos, vehículos de la cohorte y eventos que dicen los archivos de una corrida."""
    outputs = workspace / RUNS / run_id / "outputs"
    cohort = outputs / "cohorte_conciliada.csv"
    log = outputs / "sumo.log"
    if not cohort.is_file() or not log.is_file():
        return None
    lines = cohort.read_text(encoding="utf-8-sig").splitlines()[1:]
    counted = sum(1 for line in lines if line.split(";")[3] == YES)
    events = len(log_events(log.read_text(encoding="utf-8", errors="replace")))
    return len(lines), counted, events


def _check_counts(connection: Connection, workspace: Path, runs: list[Row], found: _Found) -> None:
    vehicles = _by_run(connection, "SELECT run_id, count(*) FROM simulacion.vehiculos GROUP BY 1")
    cohort = _by_run(
        connection,
        "SELECT run_id, count(*) FROM simulacion.vehiculos WHERE en_cohorte GROUP BY 1",
    )
    events = _by_run(connection, "SELECT run_id, count(*) FROM simulacion.eventos GROUP BY 1")
    for row in runs:
        run_id = str(row["run_id"])
        expected = _counts_from_files(workspace, run_id)
        if expected is None:
            if row["estado"] == "succeeded":
                found.add(run_id, "archivos de la corrida", "están en la base", "faltan")
            continue
        found.compare(run_id, "vehículos", vehicles.get(run_id, 0), expected[0])
        found.compare(run_id, "vehículos de la cohorte", cohort.get(run_id, 0), expected[1])
        found.compare(run_id, "eventos del registro de SUMO", events.get(run_id, 0), expected[2])


def _recompute(context: ProtocolContext, row: Row, stored: Row, found: _Found) -> bool:
    """Recalcula las métricas de una corrida y las compara. Devuelve si pudo verificarla."""
    run_id = str(row["run_id"])
    workspace = context.workspace
    case = context.cases.get((str(row["caso_id"]), str(row["caso_version"])))
    protocol = context.protocols.get(str(stored["protocolo_metricas_id"]))
    scenario = (
        None
        if case is None
        else context.scenarios.get((case.case_id, case.case_version, str(row["escenario_id"])))
    )
    if case is None or protocol is None or scenario is None:
        absent = [
            name
            for name, item in (
                ("el caso", case),
                ("el protocolo", protocol),
                ("el escenario", scenario),
            )
            if item is None
        ]
        found.unverify(run_id, f"falta {' y '.join(absent)} en datos/")
        return False
    folder = workspace / RUNS / run_id
    try:
        metrics = evaluate_run(
            folder / "inputs", workspace / RUNS, run_id, case, protocol, scenario=scenario
        )
    except DomainError as error:
        found.unverify(run_id, f"{error.code.value}: {error.message}")
        return False
    for name, value in metric_columns(metrics).items():
        found.compare(run_id, f"demora y métricas: {name}", stored[name], value)
    return True


def _check_series(connection: Connection, workspace: Path, runs: list[Row], found: _Found) -> None:
    """Filas de cola, de accesos y de movimientos contra ``metricas.json`` de cada corrida."""
    # Un valor por paso en cada arreglo por acceso: los pasos cuentan igual que antes (una fila por
    # paso). Se cuenta en las tablas porque esta conexión (la de carga) no lee las vistas.
    queue = _by_run(
        connection,
        "SELECT run_id, sum(jsonb_array_length(vehiculos_en_cola)) "
        "FROM simulacion.cola_por_acceso GROUP BY 1",
    )
    window = _by_run(
        connection,
        "SELECT q.run_id, sum(s.v::integer) FROM simulacion.cola_por_acceso AS q "
        "JOIN simulacion.resultados_corrida AS r ON r.run_id = q.run_id "
        "CROSS JOIN LATERAL ROWS FROM (jsonb_array_elements_text(q.vehiculos_en_cola), "
        "jsonb_array_elements_text(r.pasos_en_ventana)) AS s(v, w) "
        "WHERE s.w::boolean GROUP BY 1",
    )
    accesses = _by_run(
        connection, "SELECT run_id, count(*) FROM simulacion.resultados_acceso GROUP BY 1"
    )
    movements = _by_run(
        connection, "SELECT run_id, count(*) FROM simulacion.resultados_movimiento GROUP BY 1"
    )
    for row in runs:
        run_id = str(row["run_id"])
        folder = workspace / METRICS / str(row["caso_id"]) / run_id
        if not folder.is_dir():
            continue
        try:
            metrics = read_run_metrics(folder).metrics
        except DomainError as error:
            found.add(
                run_id, "métricas publicadas", "cargadas", f"no se pueden leer: {error.message}"
            )
            continue
        series = None if metrics.zone is None else metrics.zone.queue_series
        expected = 0 if series is None else len(series.times_s) * len(series.vehicles_by_access)
        found.compare(run_id, "filas de cola segundo a segundo", queue.get(run_id, 0), expected)
        found.compare(
            run_id, "resultados por acceso", accesses.get(run_id, 0), len(metrics.cohort.by_access)
        )
        found.compare(
            run_id,
            "resultados por movimiento",
            movements.get(run_id, 0),
            len(metrics.cohort.by_movement),
        )
        ticks = None if metrics.zone is None else metrics.zone.queue.vehicle_ticks
        if ticks is not None:
            found.compare(run_id, "vehículos en cola en la ventana", window.get(run_id, 0), ticks)


def _empty_coverage() -> Coverage:
    return Coverage(
        expected=0,
        loaded=0,
        excluded_with_decision=0,
        excluded_pending=0,
        missing=0,
        surplus=0,
        missing_keys=[],
        pending_keys=[],
        surplus_keys=[],
    )


def reconcile(
    workspace: Path,
    *,
    database: str | None = None,
    repository: Path | None = None,
    recompute: bool = True,
) -> ReconcileReport:
    """Compara la base con los archivos de ``workspace`` (ver el módulo).

    Args:
        workspace: la carpeta ``datos/``.
        database: la base (por defecto, la del servicio).
        repository: la carpeta del repositorio, para revisar también las actas de los hitos.
        recompute: volver a calcular las métricas de cada corrida desde sus archivos.
    """
    sources = discover(workspace)
    found = _Found()
    context = load_context(workspace, sources) if recompute else None
    recomputed = 0
    files = 0
    runs: list[Row] = []
    coverage = _empty_coverage()
    try:
        with lectura_estable(CARGA, database=database) as reading:
            connection = reading.connection
            files = _check_files(connection, workspace, repository, found)
            runs = _rows(
                connection,
                "SELECT run_id, caso_id, caso_version, escenario_id, estado "
                "FROM simulacion.corridas ORDER BY run_id",
            )
            coverage = _coverage(connection, workspace, sources, runs, found)
            _check_counts(connection, workspace, runs, found)
            _check_series(connection, workspace, runs, found)
            stored = {
                str(row["run_id"]): row
                for row in _rows(
                    connection,
                    "SELECT run_id, " + ", ".join(METRIC_COLUMNS) + " "
                    "FROM simulacion.resultados_corrida WHERE artefacto_metricas_id IS NOT NULL",
                )
            }
            for row in runs:
                result = stored.get(str(row["run_id"]))
                if (
                    context is not None
                    and result is not None
                    and _recompute(context, row, result, found)
                ):
                    recomputed += 1
    except Inconcluso as stopped:
        return ReconcileReport(
            status="inconclusive",
            reason=stopped.reason,
            files_checked=0,
            runs_checked=0,
            runs_recomputed=0,
            runs_unverified=0,
            differences_total=0,
            differences=[],
            unverified=[],
            coverage=coverage,
        )
    reason = reading.cambio
    status: Literal["equal", "different", "incomplete", "inconclusive"]
    if reason is not None:
        status = "inconclusive"
    elif found.items:
        status = "different"
    elif coverage.missing or coverage.excluded_pending:
        status = "incomplete"
    elif found.unverified:
        status = "inconclusive"
        reason = f"{len(found.unverified)} corridas no se pudieron verificar"
    else:
        status = "equal"
    return ReconcileReport(
        status=status,
        reason=reason,
        files_checked=files,
        runs_checked=len(runs),
        runs_recomputed=recomputed,
        runs_unverified=len(found.unverified),
        differences_total=len(found.items),
        differences=found.items[:MAX_SHOWN],
        unverified=found.unverified[:MAX_SHOWN],
        coverage=coverage,
    )
