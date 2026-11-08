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
from typing import Literal, cast

from psycopg import sql

from semaforo.bd.carga.corridas import (
    METRIC_COLUMNS,
    cohort_rows,
    delay_columns,
    log_events,
    metric_columns,
    queue_columns,
    stop_columns,
)
from semaforo.bd.carga.fuentes import Sources, discover
from semaforo.bd.carga.modelo import DATA_ROOT
from semaforo.bd.conexion import CARGA, Connection
from semaforo.bd.instantanea import Inconcluso, lectura_estable
from semaforo.bd.metricas import ProtocolContext, load_context
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.errors import DomainError
from semaforo.evaluacion.published_metrics import (
    METRICS,
    RUNS,
    protocol_fingerprint,
    read_run_metrics,
)
from semaforo.evaluacion.run_metrics import RunMetrics, evaluate_run
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
    legacy_protocol_manifests: int = 0
    differences_total: int
    differences: list[Difference]
    unverified: list[Difference]
    coverage: Coverage


def _rows(connection: Connection, query: str, params: tuple[object, ...] = ()) -> list[Row]:
    cursor = connection.execute(query.encode(), params)
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


def _recompute(context: ProtocolContext, row: Row, stored: Row, found: _Found) -> RunMetrics | None:
    """Recalcula las métricas de una corrida y compara las columnas y cada demora vehicular."""
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
        return None
    folder = workspace / RUNS / run_id
    try:
        metrics = evaluate_run(
            folder / "inputs", workspace / RUNS, run_id, case, protocol, scenario=scenario
        )
    except DomainError as error:
        found.unverify(run_id, f"{error.code.value}: {error.message}")
        return None
    for name, value in metric_columns(metrics).items():
        found.compare(run_id, f"demora y métricas: {name}", stored[name], value)
    return metrics


def _compare_value(found: _Found, where: str, field: str, actual: object, expected: object) -> None:
    """Los arreglos se cotejan posición por posición, para señalar un intercambio concreto."""
    if isinstance(expected, list) and isinstance(actual, list):
        actual_items = cast("list[object]", actual)
        expected_items = cast("list[object]", expected)
        if len(actual_items) != len(expected_items):
            found.add(where, f"{field}: longitud", len(actual_items), len(expected_items))
            return
        for index, (left, right) in enumerate(zip(actual_items, expected_items, strict=True)):
            if left != right:
                found.add(where, f"{field}[{index}]", left, right)
        return
    if actual != expected:
        found.add(where, field, actual, cast("object", expected))


def _compare_table(  # noqa: PLR0913, PLR0917 (clave, tabla y conexión son independientes)
    connection: Connection,
    table: str,
    run_id: str,
    key: str,
    expected: dict[str, Row],
    found: _Found,
) -> None:
    query = sql.SQL("SELECT * FROM {} WHERE run_id = %s").format(sql.Identifier(*table.split(".")))
    cursor = connection.execute(query, (run_id,))
    names = [column.name for column in cursor.description or []]
    rows = {
        str(row[key]): row for row in (dict(zip(names, values, strict=True)) for values in cursor)
    }
    for identifier in sorted(set(rows) | set(expected)):
        where = f"{run_id}/{table}/{identifier}"
        actual = rows.get(identifier)
        reference = expected.get(identifier)
        if actual is None or reference is None:
            found.add(
                where,
                "fila",
                "ausente" if actual is None else "presente",
                "ausente" if reference is None else "presente",
            )
            continue
        for field, value in reference.items():
            _compare_value(found, where, field, actual.get(field), value)


def _check_vehicles(  # noqa: PLR0913, PLR0917 (archivos, métricas y base)
    connection: Connection,
    workspace: Path,
    run_id: str,
    metrics: RunMetrics,
    recomputed: RunMetrics | None,
    found: _Found,
) -> None:
    cohort = workspace / RUNS / run_id / "outputs" / "cohorte_conciliada.csv"
    if not cohort.is_file():
        return
    try:
        source_rows = cohort_rows(cohort.read_bytes())
    except (DomainError, OSError) as error:
        found.add(run_id, "cohorte_conciliada.csv", "cargada", str(error))
        return
    by_vehicle = {v.vehicle_id: v for v in metrics.cohort.vehicles}
    stops = {} if metrics.zone is None else metrics.zone.vehicle_stops
    expected: dict[str, Row] = {}
    for source in source_rows:
        identifier = str(source["vehiculo_id"])
        delay = by_vehicle.get(identifier)
        expected[identifier] = {
            **source,
            "acceso": None if delay is None else delay.access_id,
            "perdida_tiempo_cohorte_s": None if delay is None else delay.time_loss_s,
            "demora_salida_cohorte_s": None if delay is None else delay.depart_delay_s,
            "fuente_demora_salida": None if delay is None else delay.depart_delay_source,
            "detenciones": None if delay is None or metrics.zone is None else stops.get(identifier),
        }
    _compare_table(connection, "simulacion.vehiculos", run_id, "vehiculo_id", expected, found)
    if recomputed is not None:
        recalculated = {v.vehicle_id: v for v in recomputed.cohort.vehicles}
        rows = _rows(
            connection,
            "SELECT vehiculo_id, perdida_tiempo_cohorte_s, demora_salida_cohorte_s "
            "FROM simulacion.vehiculos WHERE run_id = %s",
            (run_id,),
        )
        for row in rows:
            vehicle = recalculated.get(str(row["vehiculo_id"]))
            if vehicle is not None:
                found.compare(
                    run_id,
                    f"demora recalculada {vehicle.vehicle_id}: timeLoss",
                    row["perdida_tiempo_cohorte_s"],
                    vehicle.time_loss_s,
                )
                found.compare(
                    run_id,
                    f"demora recalculada {vehicle.vehicle_id}: salida",
                    row["demora_salida_cohorte_s"],
                    vehicle.depart_delay_s,
                )


def _check_events(connection: Connection, workspace: Path, run_id: str, found: _Found) -> None:
    log = workspace / RUNS / run_id / "outputs" / "sumo.log"
    if not log.is_file():
        return
    expected = {
        str(event["orden"]): event
        for event in log_events(log.read_text(encoding="utf-8", errors="replace"))
    }
    _compare_table(connection, "simulacion.eventos", run_id, "orden", expected, found)


def _check_series(
    connection: Connection,
    workspace: Path,
    runs: list[Row],
    found: _Found,
    recomputed: dict[str, RunMetrics],
) -> int:
    """Compara conteos y contenido por clave con los archivos de cada corrida."""
    # Un valor por paso en cada arreglo por acceso: los pasos cuentan igual que antes (una fila por
    # paso). Se cuenta en las tablas porque esta conexión (la de carga) no lee las vistas.
    queue = _by_run(
        connection,
        "SELECT run_id, sum(cardinality(vehiculos_en_cola)) "
        "FROM simulacion.cola_por_acceso GROUP BY 1",
    )
    window = _by_run(
        connection,
        "SELECT q.run_id, sum(s.v::integer) FROM simulacion.cola_por_acceso AS q "
        "JOIN simulacion.resultados_corrida AS r ON r.run_id = q.run_id "
        "CROSS JOIN LATERAL ROWS FROM (unnest(q.vehiculos_en_cola), "
        "unnest(r.pasos_en_ventana)) AS s(v, w) "
        "WHERE s.w GROUP BY 1",
    )
    accesses = _by_run(
        connection, "SELECT run_id, count(*) FROM simulacion.resultados_acceso GROUP BY 1"
    )
    movements = _by_run(
        connection, "SELECT run_id, count(*) FROM simulacion.resultados_movimiento GROUP BY 1"
    )
    legacy = 0
    for row in runs:
        run_id = str(row["run_id"])
        _check_events(connection, workspace, run_id, found)
        folder = workspace / METRICS / str(row["caso_id"]) / run_id
        if not folder.is_dir():
            continue
        try:
            published = read_run_metrics(folder)
            metrics = published.metrics
        except DomainError as error:
            found.add(
                run_id, "métricas publicadas", "cargadas", f"no se pueden leer: {error.message}"
            )
            continue
        if published.manifest.protocol_sha256 is None:
            legacy += 1
        else:
            try:
                current = protocol_fingerprint(workspace, metrics.protocol_id)
            except DomainError as error:
                found.add(
                    run_id,
                    "huella del protocolo",
                    published.manifest.protocol_sha256,
                    error.message,
                )
            else:
                _compare_value(
                    found,
                    run_id,
                    "huella del protocolo",
                    current,
                    published.manifest.protocol_sha256,
                )
        series = None if metrics.zone is None else metrics.zone.queue_series
        zone = metrics.zone
        queues = {} if zone is None else zone.queue_by_access
        stops = {} if zone is None else zone.stops_by_access
        expected = 0 if series is None else len(series.times_s) * len(series.vehicles_by_access)
        found.compare(run_id, "filas de cola segundo a segundo", queue.get(run_id, 0), expected)
        found.compare(
            run_id,
            "resultados por acceso",
            accesses.get(run_id, 0),
            len(set(metrics.cohort.by_access) | set(queues) | set(stops)),
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
        top = _rows(
            connection,
            "SELECT pasos_cola_s, pasos_en_ventana FROM simulacion.resultados_corrida "
            "WHERE run_id = %s",
            (run_id,),
        )
        if top:
            for field, value in {
                "pasos_cola_s": None if series is None else list(series.times_s),
                "pasos_en_ventana": None if series is None else list(series.in_window),
            }.items():
                _compare_value(found, run_id, field, top[0][field], value)
        queue_expected: dict[str, Row] = (
            {}
            if series is None
            else {
                access: {"vehiculos_en_cola": list(values)}
                for access, values in series.vehicles_by_access.items()
            }
        )
        _compare_table(
            connection, "simulacion.cola_por_acceso", run_id, "acceso", queue_expected, found
        )
        access_expected = {
            access: {
                "con_cohorte": access in metrics.cohort.by_access,
                **delay_columns(metrics.cohort.by_access.get(access)),
                **queue_columns(queues.get(access)),
                **stop_columns(stops.get(access)),
            }
            for access in set(metrics.cohort.by_access) | set(queues) | set(stops)
        }
        _compare_table(
            connection, "simulacion.resultados_acceso", run_id, "acceso", access_expected, found
        )
        movement_expected = {
            movement: delay_columns(summary)
            for movement, summary in metrics.cohort.by_movement.items()
        }
        _compare_table(
            connection,
            "simulacion.resultados_movimiento",
            run_id,
            "movimiento_id",
            movement_expected,
            found,
        )
        _check_vehicles(connection, workspace, run_id, metrics, recomputed.get(run_id), found)
    return legacy


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
    recalculated: dict[str, RunMetrics] = {}
    legacy = 0
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
                if context is not None and result is not None:
                    metrics = _recompute(context, row, result, found)
                    if metrics is not None:
                        recalculated[str(row["run_id"])] = metrics
                        recomputed += 1
            legacy = _check_series(connection, workspace, runs, found, recalculated)
    except Inconcluso as stopped:
        return ReconcileReport(
            status="inconclusive",
            reason=stopped.reason,
            files_checked=0,
            runs_checked=0,
            runs_recomputed=0,
            runs_unverified=0,
            legacy_protocol_manifests=0,
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
        legacy_protocol_manifests=legacy,
        differences_total=len(found.items),
        differences=found.items[:MAX_SHOWN],
        unverified=found.unverified[:MAX_SHOWN],
        coverage=coverage,
    )
