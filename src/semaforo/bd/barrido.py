"""Barrido de cegado sobre una base real (DEV31 F4c, C3.2 y C3.5).

Recorre **todas** las tablas y vistas del proyecto, tal como las lista el catálogo de PostgreSQL
(las tablas futuras entran solas), una vez como lector y otra como panel:

- el panel solo puede leer las vistas aprobadas (``PANEL_VIEWS``): cualquier otra relación tiene que
  negarle el acceso;
- el lector puede abrir todas las relaciones (el cegado le quita filas, no relaciones);
- ninguna relación visible para ese usuario puede mostrar rastros de un escenario cegado: su
  identificador, el de sus corridas, el de sus búsquedas ni el de sus archivos.

Las columnas justificadas por el diseño (el nombre del escenario de prueba en las asignaciones y en
la lista de cegados, que ADR07 hace público) no cuentan como filtración.

Límite: solo busca identificadores. Las duraciones numéricas de los planes exclusivos de la prueba
no se buscan aquí (un número como «30» aparece en cualquier parte); se prueban con un valor
inconfundible en una base desechable (``test_bd_reglas.py``).

Nunca escribe nada. Usa a ``semaforo_admin`` solo para leer el catálogo y los identificadores
cegados, que ni el lector ni el panel pueden ver.
"""

from typing import Literal

import psycopg
from psycopg import sql

from semaforo.bd.conexion import ADMIN, LECTURA, PANEL, Connection, connect
from semaforo.bd.ddl import PANEL_VIEWS
from semaforo.dominio.base_model import FrozenModel

__all__ = ["Leak", "RoleSweep", "SweepReport", "sweep", "sweep_exit_code"]

SCHEMAS = (
    "control",
    "caso",
    "experimento",
    "simulacion",
    "referencias",
    "aprendizaje",
    "estimacion",
    "evaluacion",
    "vistas",
)
# Columnas que el diseño justifica como públicas (ADR07): el nombre del escenario de prueba.
JUSTIFIED = {
    "experimento.asignaciones": ["escenario_id"],
    "control.escenarios_cegados": ["escenario_id"],
}
MAX_SHOWN = 20
INTEGRITY_EXIT = 5


class Leak(FrozenModel):
    """Una relación que muestra rastros de un escenario cegado."""

    relation: str
    rows: int


class RoleSweep(FrozenModel):
    """Lo que se comprobó para un usuario."""

    role: str
    relations: int
    readable: int
    denied: int
    unexpected_denials: list[str]
    unexpected_reads: list[str]
    leaks: list[Leak]


class SweepReport(FrozenModel):
    """Resultado del barrido de cegado."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["ok", "falla"]
    hidden_scenarios: int
    marks: int
    relations: int
    roles: list[RoleSweep]
    note: str | None


def _relations(admin: Connection) -> list[tuple[str, str]]:
    return [
        (str(schema), str(name))
        for schema, name in admin.execute(
            "SELECT n.nspname, c.relname FROM pg_class AS c "
            "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE n.nspname = ANY(%s) AND c.relkind IN ('r', 'p', 'v') ORDER BY 1, 2",
            (list(SCHEMAS),),
        )
    ]


def _marks(admin: Connection) -> tuple[int, list[str]]:
    """Los escenarios cegados y todo identificador que cuelga de ellos."""
    hidden = [
        str(row[0]) for row in admin.execute("SELECT escenario_id FROM control.escenarios_cegados")
    ]
    if not hidden:
        return 0, []
    marks = set(hidden)
    for query in (
        "SELECT run_id FROM simulacion.corridas WHERE escenario_id = ANY(%s)",
        "SELECT busqueda_id FROM simulacion.busquedas WHERE escenario_id = ANY(%s)",
        "SELECT artefacto_id FROM control.archivo_escenarios WHERE escenario_id = ANY(%s)",
    ):
        marks.update(str(row[0]) for row in admin.execute(query.encode(), (hidden,)))
    return len(hidden), sorted(marks)


def _pattern(mark: str) -> str:
    escaped = mark.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _readable(connection: Connection, schema: str, name: str) -> bool:
    """Si el usuario puede abrir la relación (sin leer ninguna fila)."""
    try:
        connection.execute(sql.SQL("SELECT 1 FROM {} LIMIT 0").format(sql.Identifier(schema, name)))
    except psycopg.errors.InsufficientPrivilege:
        return False
    return True


def _leak_rows(connection: Connection, schema: str, name: str, patterns: list[str]) -> int:
    """Cuántas filas de la relación muestran una marca fuera de las columnas justificadas."""
    removed = JUSTIFIED.get(f"{schema}.{name}", [])
    query = sql.SQL(
        "SELECT count(*) FROM {} AS t WHERE (to_jsonb(t) - %s::text[])::text LIKE ANY (%s)"
    ).format(sql.Identifier(schema, name))
    row = connection.execute(query, (removed, patterns)).fetchone()
    return 0 if row is None else int(row[0])


def _sweep_role(
    role: str,
    database: str | None,
    relations: list[tuple[str, str]],
    patterns: list[str],
) -> RoleSweep:
    readable = denied = 0
    unexpected_denials: list[str] = []
    unexpected_reads: list[str] = []
    leaks: list[Leak] = []
    with connect(role, database=database, autocommit=True) as connection:
        for schema, name in relations:
            full = f"{schema}.{name}"
            allowed = role == LECTURA or (schema == "vistas" and name in PANEL_VIEWS)
            opens = _readable(connection, schema, name)
            if not opens:
                denied += 1
                if allowed:
                    unexpected_denials.append(full)
                continue
            readable += 1
            if not allowed:
                unexpected_reads.append(full)
                continue
            found = _leak_rows(connection, schema, name, patterns) if patterns else 0
            if found:
                leaks.append(Leak(relation=full, rows=found))
    return RoleSweep(
        role=role,
        relations=len(relations),
        readable=readable,
        denied=denied,
        unexpected_denials=unexpected_denials[:MAX_SHOWN],
        unexpected_reads=unexpected_reads[:MAX_SHOWN],
        leaks=leaks[:MAX_SHOWN],
    )


def sweep(database: str | None = None) -> SweepReport:
    """Barrido de cegado de ``database`` (por defecto, la base del servicio).

    Raises:
        BdError: si no hay conexión con la base o falta el servicio de algún usuario.
    """
    with connect(ADMIN, database=database, autocommit=True) as admin:
        relations = _relations(admin)
        hidden, marks = _marks(admin)
    patterns = [_pattern(mark) for mark in marks]
    roles = [_sweep_role(role, database, relations, patterns) for role in (LECTURA, PANEL)]
    clean = all(
        not (item.unexpected_denials or item.unexpected_reads or item.leaks) for item in roles
    )
    note = (
        None
        if hidden
        else "No hay escenarios cegados: solo se comprobó el reparto de permisos entre relaciones."
    )
    return SweepReport(
        status="ok" if clean else "falla",
        hidden_scenarios=hidden,
        marks=len(marks),
        relations=len(relations),
        roles=roles,
        note=note,
    )


def sweep_exit_code(report: SweepReport) -> int:
    """0 si el barrido no encontró nada fuera de lugar; 5 si encontró algo."""
    return 0 if report.status == "ok" else INTEGRITY_EXIT
