"""La base coincide con los archivos: mismos conteos y misma demora recalculada (DEV31 F4; QA33).

``reconcile`` compara la base con los archivos de ``datos/`` por otro camino que el cargador:

1. **Archivos:** cada archivo íntegro que conoce la base existe, pesa lo mismo y da la misma huella.
2. **Conteos de cada corrida:** vehículos, vehículos de la cohorte y eventos de la base contra las
   líneas de ``cohorte_conciliada.csv`` y de ``sumo.log``; filas de la cola paso a paso contra
   ``metricas.json``; filas por acceso y por movimiento; y la suma de vehículos en cola de la
   ventana de medición.
3. **Demora recalculada:** vuelve a calcular las métricas de cada corrida desde sus archivos con el
   código oficial (``evaluate_run``) y compara **cada columna de métricas** de
   ``resultados_corrida`` con lo que está en la base.

No escribe nada. Una diferencia no se corrige aquí: se informa.
"""

import math
from pathlib import Path
from typing import Literal

from semaforo.bd.carga.corridas import METRIC_COLUMNS, log_events, metric_columns
from semaforo.bd.conexion import CARGA, Connection, connect
from semaforo.bd.metricas import ProtocolContext, load_context
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.errors import DomainError
from semaforo.evaluacion.published_metrics import METRICS, RUNS, read_run_metrics
from semaforo.evaluacion.run_metrics import evaluate_run
from semaforo.trazabilidad.hashing import sha256_file

__all__ = ["Difference", "ReconcileReport", "reconcile"]

MAX_SHOWN = 200
YES = "sí"
TOLERANCE = 1e-12

Row = dict[str, object]


class Difference(FrozenModel):
    """Una cosa que no coincide: dónde, qué y los dos valores."""

    where: str
    item: str
    database: str
    files: str


class ReconcileReport(FrozenModel):
    """Resultado de ``bd conciliar`` (sin rutas de la máquina)."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["equal", "different"]
    files_checked: int
    runs_checked: int
    runs_recomputed: int
    differences_total: int
    differences: list[Difference]


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

    def add(self, where: str, item: str, database: object, files: object) -> None:
        self.items.append(
            Difference(where=where, item=item, database=str(database), files=str(files))
        )

    def compare(self, where: str, item: str, database: object, files: object) -> None:
        if not _same(database, files):
            self.add(where, item, database, files)


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


def _recompute(context: ProtocolContext, row: Row, stored: Row, found: _Found) -> None:
    run_id = str(row["run_id"])
    workspace = context.workspace
    case = context.cases[(str(row["caso_id"]), str(row["caso_version"]))]
    protocol = context.protocols[str(stored["protocolo_metricas_id"])]
    scenario = context.scenarios[(case.case_id, case.case_version, str(row["escenario_id"]))]
    folder = workspace / RUNS / run_id
    metrics = evaluate_run(
        folder / "inputs", workspace / RUNS, run_id, case, protocol, scenario=scenario
    )
    for name, value in metric_columns(metrics).items():
        found.compare(run_id, f"demora y métricas: {name}", stored[name], value)


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
    found = _Found()
    context = load_context(workspace) if recompute else None
    recomputed = 0
    with connect(CARGA, database=database, autocommit=True) as connection:
        files = _check_files(connection, workspace, repository, found)
        runs = _rows(
            connection,
            "SELECT run_id, caso_id, caso_version, escenario_id, estado "
            "FROM simulacion.corridas ORDER BY run_id",
        )
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
            if context is None or result is None:
                continue
            try:
                _recompute(context, row, result, found)
            except DomainError as error:
                found.add(str(row["run_id"]), "recálculo", "métricas en la base", error.message)
            recomputed += 1
    shown = found.items[:MAX_SHOWN]
    return ReconcileReport(
        status="equal" if not found.items else "different",
        files_checked=files,
        runs_checked=len(runs),
        runs_recomputed=recomputed,
        differences_total=len(found.items),
        differences=shown,
    )
