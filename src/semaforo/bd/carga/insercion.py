"""Escritura de una unidad: comparar con lo que ya hay y agregar solo lo nuevo (DEV31 F3).

Para cada tabla, en el orden de sus relaciones:

1. las filas de la unidad van a una tabla temporal con la misma forma (``LIKE``);
2. si una clave ya está en la base con **otro** contenido, es un conflicto: no se escribe nada;
3. si está con el mismo contenido, se salta (cargar dos veces no duplica, B9);
4. el resto se agrega con un solo ``INSERT ... SELECT``, que pasa por las reglas, los disparadores
   y la seguridad por filas de la tabla.

Todo dentro de la transacción de la unidad: si algo falla, no queda nada. Los nombres de tablas,
columnas y tipos salen del catálogo de la propia base, nunca de los archivos.
"""

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from psycopg import sql
from psycopg.types.json import Jsonb

from semaforo.bd.carga.modelo import CargaError, Row
from semaforo.bd.conexion import Connection
from semaforo.dominio.errors import ErrorCode

__all__ = [
    "SCHEMAS",
    "Catalog",
    "KeyConflict",
    "TableInfo",
    "WriteResult",
    "write_rows",
]

SCHEMAS = ("control", "caso", "experimento", "simulacion", "aprendizaje", "evaluacion")
COMMON = frozenset({"carga_id", "artefacto_id"})
# Columnas que cambian entre dos cargas del mismo archivo y no cuentan para comparar.
VOLATILE: dict[str, frozenset[str]] = {"control.artefactos": frozenset({"registrado_en"})}
TYPES: dict[str, sql.SQL] = {
    "text": sql.SQL("text"),
    "integer": sql.SQL("integer"),
    "bigint": sql.SQL("bigint"),
    "double precision": sql.SQL("double precision"),
    "boolean": sql.SQL("boolean"),
    "timestamp with time zone": sql.SQL("timestamptz"),
    "date": sql.SQL("date"),
    "jsonb": sql.SQL("jsonb"),
    "control.huella": sql.SQL("control.huella"),
}


@dataclass(frozen=True)
class TableInfo:
    """Una tabla de la base: columnas en orden, tipos, obligatorias y clave primaria."""

    full: str
    columns: tuple[str, ...]
    types: dict[str, str]
    required: frozenset[str]
    primary: tuple[str, ...]

    @property
    def identifier(self) -> sql.Identifier:
        schema, name = self.full.split(".")
        return sql.Identifier(schema, name)


@dataclass(frozen=True)
class Catalog:
    """Las tablas del proyecto según la propia base, y un orden que respeta sus relaciones."""

    tables: dict[str, TableInfo]
    order: tuple[str, ...]

    @classmethod
    def load(cls, connection: Connection) -> "Catalog":
        columns: dict[str, list[tuple[str, str, bool]]] = {}
        for schema, table, column, kind, not_null in connection.execute(
            "SELECT n.nspname, c.relname, a.attname, format_type(a.atttypid, a.atttypmod), "
            "a.attnotnull FROM pg_attribute AS a "
            "JOIN pg_class AS c ON c.oid = a.attrelid "
            "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE c.relkind = 'r' AND n.nspname = ANY(%s) AND a.attnum > 0 "
            "AND NOT a.attisdropped ORDER BY n.nspname, c.relname, a.attnum",
            (list(SCHEMAS),),
        ):
            columns.setdefault(f"{schema}.{table}", []).append(
                (str(column), str(kind), bool(not_null))
            )
        primary: dict[str, tuple[str, ...]] = {}
        for schema, table, names in connection.execute(
            "SELECT n.nspname, c.relname, array_agg(a.attname ORDER BY k.ord) "
            "FROM pg_constraint AS p JOIN pg_class AS c ON c.oid = p.conrelid "
            "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
            "CROSS JOIN LATERAL unnest(p.conkey) WITH ORDINALITY AS k(attnum, ord) "
            "JOIN pg_attribute AS a ON a.attrelid = c.oid AND a.attnum = k.attnum "
            "WHERE p.contype = 'p' AND n.nspname = ANY(%s) GROUP BY n.nspname, c.relname",
            (list(SCHEMAS),),
        ):
            primary[f"{schema}.{table}"] = tuple(str(n) for n in names)
        edges: list[tuple[str, str]] = [
            (str(child), str(parent))
            for child, parent in connection.execute(
                "SELECT conrelid::regclass::text, confrelid::regclass::text "
                "FROM pg_constraint WHERE contype = 'f'"
            )
        ]
        tables = {
            full: TableInfo(
                full=full,
                columns=tuple(name for name, _, _ in found),
                types={name: kind for name, kind, _ in found},
                required=frozenset(name for name, _, not_null in found if not_null),
                primary=primary[full],
            )
            for full, found in columns.items()
        }
        return cls(tables=tables, order=_topological(tables, edges))


def _topological(tables: dict[str, TableInfo], edges: list[tuple[str, str]]) -> tuple[str, ...]:
    """Las tablas de modo que cada una venga después de las que referencia."""
    parents: dict[str, set[str]] = {name: set() for name in tables}
    for child, parent in edges:
        if child in parents and parent in parents and child != parent:
            parents[child].add(parent)
    order: list[str] = []
    done: set[str] = set()
    while len(order) < len(tables):
        ready = sorted(n for n in tables if n not in done and parents[n] <= done)
        if not ready:
            raise CargaError(ErrorCode.INPUT_SCHEMA, "las relaciones de la base forman un ciclo")
        order.extend(ready)
        done.update(ready)
    return tuple(order)


@dataclass(frozen=True)
class KeyConflict:
    """Una clave que ya está en la base con otro contenido."""

    table: str
    key: str


@dataclass(frozen=True)
class WriteResult:
    """Filas nuevas e iguales por tabla, y los conflictos (si hay, no se escribió nada)."""

    new: dict[str, int]
    same: dict[str, int]
    conflicts: list[KeyConflict]


def _number(value: object) -> object:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return float(value)


def _integer(value: object) -> object:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _moment(value: object) -> object:
    try:
        moment = datetime.fromisoformat(value) if isinstance(value, str) else value
    except ValueError:
        return None
    return moment if isinstance(moment, datetime) and moment.utcoffset() is not None else None


def _boolean(value: object) -> object:
    return value if isinstance(value, bool) else None


def _text(value: object) -> object:
    return value if isinstance(value, str) else None


# Cada tipo de columna: cómo se convierte el valor y qué se dice si no corresponde (None).
_CONVERSIONS: dict[str, tuple[Callable[[object], object], str]] = {
    "double precision": (_number, "se esperaba un número finito"),
    "integer": (_integer, "se esperaba un entero"),
    "bigint": (_integer, "se esperaba un entero"),
    "boolean": (_boolean, "se esperaba verdadero o falso"),
    "timestamp with time zone": (_moment, "se esperaba una fecha con zona horaria"),
}


def _value(table: str, column: str, kind: str, value: object) -> object:
    """El valor con el tipo de la columna; ``CargaError`` si no corresponde."""
    if value is None:
        return None
    if kind == "jsonb":
        return Jsonb(value)
    convert, message = _CONVERSIONS.get(kind, (_text, "se esperaba un texto"))
    converted = convert(value)
    if converted is None:
        raise CargaError(ErrorCode.INPUT_SCHEMA, message, f"{table}.{column}")
    return converted


def _checked(info: TableInfo, rows: Sequence[Row]) -> list[Row]:
    """Las filas con todas sus columnas, sin columnas desconocidas y sin claves repetidas."""
    known = set(info.columns)
    by_key: dict[tuple[object, ...], Row] = {}
    for row in rows:
        unknown = sorted(set(row) - known)
        if unknown:
            raise CargaError(ErrorCode.INPUT_SCHEMA, f"columnas desconocidas {unknown}", info.full)
        missing = sorted(c for c in info.required if row.get(c) is None)
        if missing:
            raise CargaError(ErrorCode.INPUT_SCHEMA, f"faltan columnas {missing}", info.full)
        key = tuple(row[c] for c in info.primary)
        previous = by_key.get(key)
        if previous is None:
            by_key[key] = row
        elif _content(previous) != _content(row):
            raise CargaError(
                ErrorCode.INPUT_SCHEMA,
                f"dos filas con la clave {key} y distinto contenido",
                info.full,
            )
        # La misma fila desde dos archivos (un plan en la traza y en la etiqueta): queda la
        # primera, con su archivo de origen.
    return list(by_key.values())


def _content(row: Row) -> Row:
    return {column: value for column, value in row.items() if column not in COMMON}


def _temporary(info: TableInfo) -> sql.Identifier:
    return sql.Identifier("carga_" + info.full.replace(".", "__"))


def _stage(connection: Connection, info: TableInfo, rows: list[Row]) -> sql.Identifier:
    """Pone ``rows`` en una tabla temporal con la forma de ``info``; devuelve su nombre."""
    temporary = _temporary(info)
    connection.execute(
        sql.SQL("CREATE TEMP TABLE IF NOT EXISTS {} (LIKE {}) ON COMMIT DROP").format(
            temporary, info.identifier
        )
    )
    connection.execute(sql.SQL("TRUNCATE {}").format(temporary))
    columns = info.columns
    arrays = [
        [_value(info.full, column, info.types[column], row.get(column)) for row in rows]
        for column in columns
    ]
    casts = sql.SQL(", ").join(
        sql.SQL("%s::{}[]").format(TYPES[info.types[column]]) for column in columns
    )
    connection.execute(
        sql.SQL("INSERT INTO {} ({}) SELECT * FROM unnest({})").format(
            temporary, sql.SQL(", ").join(map(sql.Identifier, columns)), casts
        ),
        arrays,
    )
    return temporary


def _match(info: TableInfo) -> sql.Composed:
    return sql.SQL(" AND ").join(
        sql.SQL("t.{0} = s.{0}").format(sql.Identifier(column)) for column in info.primary
    )


def _compared(info: TableInfo) -> list[str]:
    skip = COMMON | VOLATILE.get(info.full, frozenset())
    return [column for column in info.columns if column not in skip]


def _conflicts(connection: Connection, info: TableInfo, temporary: sql.Identifier) -> list[str]:
    compared = _compared(info)
    left = sql.SQL(", ").join(sql.SQL("t.{}").format(sql.Identifier(c)) for c in compared)
    right = sql.SQL(", ").join(sql.SQL("s.{}").format(sql.Identifier(c)) for c in compared)
    keys = sql.SQL(", ").join(sql.SQL("s.{}::text").format(sql.Identifier(c)) for c in info.primary)
    query = sql.SQL(
        "SELECT concat_ws('|', {keys}) FROM {temporary} AS s JOIN {table} AS t ON {match} "
        "WHERE ROW({left}) IS DISTINCT FROM ROW({right}) ORDER BY 1 LIMIT 20"
    ).format(
        keys=keys,
        temporary=temporary,
        table=info.identifier,
        match=_match(info),
        left=left,
        right=right,
    )
    return [str(row[0]) for row in connection.execute(query)]


def _insert_new(connection: Connection, info: TableInfo, temporary: sql.Identifier) -> int:
    columns = sql.SQL(", ").join(map(sql.Identifier, info.columns))
    query = sql.SQL(
        "INSERT INTO {table} ({columns}) SELECT {columns} FROM {temporary} AS s "
        "WHERE NOT EXISTS (SELECT 1 FROM {table} AS t WHERE {match})"
    ).format(table=info.identifier, columns=columns, temporary=temporary, match=_match(info))
    return connection.execute(query).rowcount


def write_rows(
    connection: Connection, catalog: Catalog, rows: dict[str, list[Row]], carga_id: str
) -> WriteResult:
    """Escribe ``rows`` (por tabla) dentro de la transacción en curso.

    Si alguna clave ya existe con otro contenido, devuelve los conflictos sin escribir nada más
    (quien llama deshace la transacción).
    """
    unknown = sorted(set(rows) - set(catalog.tables))
    if unknown:
        raise CargaError(ErrorCode.INPUT_SCHEMA, f"tablas desconocidas {unknown}")
    new: dict[str, int] = {}
    same: dict[str, int] = {}
    staged: list[tuple[TableInfo, sql.Identifier, int]] = []
    for name in catalog.order:
        if not rows.get(name):
            continue
        info = catalog.tables[name]
        checked = _checked(info, _with_load(info, rows[name], carga_id))
        staged.append((info, _stage(connection, info, checked), len(checked)))
    conflicts = [
        KeyConflict(info.full, key)
        for info, temporary, _ in staged
        for key in _conflicts(connection, info, temporary)
    ]
    if conflicts:
        return WriteResult(new={}, same={}, conflicts=conflicts)
    for info, temporary, count in staged:
        inserted = _insert_new(connection, info, temporary)
        new[info.full] = inserted
        same[info.full] = count - inserted
    return WriteResult(new=new, same=same, conflicts=[])


def _with_load(info: TableInfo, rows: Iterable[Row], carga_id: str) -> list[Row]:
    if "carga_id" not in info.columns:
        return list(rows)
    return [{**row, "carga_id": carga_id} for row in rows]
