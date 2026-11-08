"""Lo que el panel lee de la base (DEV31 F5): solo vistas aprobadas y solo con ``semaforo_panel``.

El rol no tiene permiso sobre ninguna tabla, así que el cegado no depende de este código: lo que una
vista no devuelve, el panel no lo puede publicar. Todo se lee en una sola instantánea de solo
lectura, para que las cifras de las distintas páginas sean de la misma base.

La cola se guarda paso a paso (un valor por segundo, por acceso y por corrida). Para que el panel
se abra con doble clic se resume aquí, en la propia base, a un promedio por intervalo de
``QUEUE_BIN_S`` segundos; el dato completo sigue en ``vistas.cola_por_segundo``.
"""

import math
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from semaforo.bd.conexion import PANEL, BdError, connect
from semaforo.dominio.errors import ErrorCode

__all__ = ["QUEUE_BIN_S", "Row", "plain", "read_panel_rows"]

type Row = dict[str, Any]

QUEUE_BIN_S = 60
ROUND_DIGITS = 2

# Cada vista del panel, con su orden estable: dos generaciones de la misma base dan lo mismo.
QUERIES = {
    "base": "SELECT * FROM vistas.estado_base",
    "casos": "SELECT * FROM vistas.caso_resumen ORDER BY caso_id, caso_version",
    "movimientos": "SELECT * FROM vistas.caso_movimientos ORDER BY caso_id, caso_version, orden",
    "tramos": "SELECT * FROM vistas.caso_tramos ORDER BY caso_id, caso_version, orden",
    "planes": "SELECT * FROM vistas.planes_resumen ORDER BY plan_id",
    "escenarios": "SELECT * FROM vistas.escenarios_detalle ORDER BY escenario_id",
    "zonas": "SELECT * FROM vistas.zona_escenario ORDER BY escenario_id, particion_id",
    "demanda": (
        "SELECT * FROM vistas.demanda_escenario ORDER BY escenario_id, movimiento_id, clase_id"
    ),
    "protocolos": "SELECT * FROM vistas.protocolos_resumen ORDER BY protocolo_id",
    "corridas": "SELECT * FROM vistas.corridas_resumen ORDER BY run_id",
    "procedencia": "SELECT * FROM vistas.corridas_procedencia ORDER BY run_id",
    "accesos": "SELECT * FROM vistas.resultados_acceso ORDER BY run_id, acceso",
    "resultados_movimiento": (
        "SELECT * FROM vistas.resultados_movimiento ORDER BY run_id, movimiento_id"
    ),
    "busquedas": "SELECT * FROM vistas.busquedas_resumen ORDER BY busqueda_id",
    "candidatos": "SELECT * FROM vistas.candidatos_resumen ORDER BY busqueda_id, orden",
    "candidato_semillas": (
        "SELECT * FROM vistas.candidato_semillas ORDER BY busqueda_id, candidato_id, etapa, semilla"
    ),
    "comparadores": "SELECT * FROM vistas.comparadores_resumen ORDER BY comparador_id",
    "exclusiones": "SELECT * FROM vistas.exclusiones ORDER BY archivo",
    "hitos": "SELECT * FROM vistas.estado_hitos ORDER BY registrado_en, hito_id",
    "etiquetas": "SELECT * FROM vistas.etiquetas_entrenamiento ORDER BY etiqueta_id",
    "metricas_modelos": (
        "SELECT * FROM vistas.metricas_modelos ORDER BY entrenamiento_id, metrica, alcance"
    ),
    "consultas": "SELECT * FROM vistas.consultas_resumen ORDER BY request_id",
    "indicadores": "SELECT * FROM vistas.indicadores_finales ORDER BY indicador_id",
}
QUEUE_QUERY = (
    "SELECT run_id, acceso, floor(tiempo_s / %(bin)s) * %(bin)s AS desde_s, "
    "avg(vehiculos_en_cola)::double precision AS media, bool_or(en_ventana) AS en_ventana "
    "FROM vistas.cola_por_segundo GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"
)


def plain(value: object) -> object:
    """Un valor que el JSON representa sin perder su significado.

    Un número no finito no es un dato: queda vacío, nunca como texto ni como cero.
    """
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _clean(row: Row) -> Row:
    return {key: plain(value) for key, value in row.items()}


def _queue(rows: list[Row]) -> dict[str, Row]:
    """La cola de cada corrida: los intervalos y, por acceso, su promedio en cada uno."""
    runs: dict[str, Row] = {}
    for row in rows:
        run = runs.setdefault(str(row["run_id"]), {"desde_s": [], "en_ventana": [], "accesos": {}})
        start = float(row["desde_s"])
        if start not in run["desde_s"]:
            run["desde_s"].append(start)
            run["en_ventana"].append(bool(row["en_ventana"]))
        run["accesos"].setdefault(str(row["acceso"]), []).append(
            round(float(row["media"]), ROUND_DIGITS)
        )
    return runs


def read_panel_rows(database: str | None = None) -> dict[str, Any]:
    """Todo lo que el panel muestra, leído en una instantánea con ``semaforo_panel``.

    Raises:
        BdError: DEPENDENCY_MISSING si el rol no se puede conectar; INPUT_SCHEMA si a esa base le
            faltan las vistas del panel (es de una versión anterior del esquema).
    """
    with connect(PANEL, database=database) as connection:
        connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        connection.read_only = True
        try:
            with connection.cursor(row_factory=dict_row) as cursor:
                found: dict[str, Any] = {
                    name: [_clean(row) for row in cursor.execute(query.encode()).fetchall()]
                    for name, query in QUERIES.items()
                }
                found["cola"] = _queue(
                    cursor.execute(QUEUE_QUERY.encode(), {"bin": QUEUE_BIN_S}).fetchall()
                )
        except (psycopg.errors.UndefinedTable, psycopg.errors.InsufficientPrivilege) as error:
            first = str(error).strip().splitlines()[0]
            raise BdError(
                ErrorCode.INPUT_SCHEMA,
                f"la base no tiene las vistas del panel ({first}): "
                "es de otra versión del esquema; reconstrúyala con bd reconstruir",
                "base",
            ) from error
    return found
