"""El diseño de la base, leído de ``docs/bd/esquema.toml`` y verificado (DEV31 F1 y F3).

``esquema.toml`` es la fuente única: de él salen el diccionario de datos y el SQL que crea la base
(``semaforo.bd.ddl``). Este módulo solo lee y comprueba el diseño; no se conecta a ninguna base.

Comprueba, entre otras cosas: nombres válidos y sin repetir; tipos conocidos; claves primarias sin
columnas vacías; que cada clave foránea apunte a la clave primaria o a una clave única de la tabla
referida, con los mismos tipos y con su obligatoriedad coherente; y que el cegado de cada tabla
esté bien declarado.
"""

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

__all__ = [
    "BASE_TYPES",
    "Column",
    "Design",
    "ForeignKey",
    "Rule",
    "SchemaError",
    "Table",
    "load",
    "verify",
]

BASE_TYPES = frozenset(
    {
        "text",
        "integer",
        "bigint",
        "double precision",
        "boolean",
        "timestamptz",
        "date",
        "jsonb",
        "integer[]",
        "double precision[]",
        "boolean[]",
    }
)
NAME = re.compile(r"^[a-z][a-z0-9_]*$")
PARENT = re.compile(r"^([a-z_]+\.[a-z_]+)\(([a-z_,]+)\)$")
SCENARIOS = "experimento.escenarios"
PARTITIONS = "experimento.particiones"
EXPERIMENTS = "evaluacion.experimentos"
APERTURA_PARTICION_ARGS = 2

Record = Mapping[str, object]


class SchemaError(Exception):
    """El archivo del esquema no tiene la forma esperada."""


@dataclass(frozen=True)
class Column:
    nombre: str
    tipo: str
    nulo: bool
    unidad: str | None
    descripcion: str
    origen: str
    regla: str | None
    comun: bool = False


@dataclass(frozen=True)
class ForeignKey:
    columnas: tuple[str, ...]
    referencia: str
    referidas: tuple[str, ...]
    opcional: bool
    uno_a_uno: bool
    nota: str | None
    comun: bool = False


@dataclass(frozen=True)
class Rule:
    nombre: str
    sql: str
    descripcion: str


@dataclass(frozen=True)
class Table:
    esquema: str
    nombre: str
    descripcion: str
    grano: str
    origen: str
    fuente: str
    filas_dev16: str
    cegado: str
    propuesta: bool
    excepcion: str | None
    visible_porque: str | None
    columnas: tuple[Column, ...]
    clave_primaria: tuple[str, ...]
    claves_foraneas: tuple[ForeignKey, ...]
    unicas: tuple[tuple[str, ...], ...]
    reglas: tuple[Rule, ...]
    indices: tuple[tuple[str, ...], ...]

    @property
    def full(self) -> str:
        return f"{self.esquema}.{self.nombre}"

    def column(self, name: str) -> Column | None:
        return next((c for c in self.columnas if c.nombre == name), None)


@dataclass(frozen=True)
class Design:
    version: str
    fecha: str
    motor: str
    estado: str
    esquemas: tuple[tuple[str, str], ...]
    tipos: dict[str, tuple[str, str, str]]
    roles: tuple[tuple[str, str, str], ...]
    funciones: tuple[tuple[str, str, str], ...]
    vistas: tuple[tuple[str, str, tuple[str, ...]], ...]
    tablas: tuple[Table, ...]

    def table(self, full: str) -> Table | None:
        return next((t for t in self.tablas if t.full == full), None)


# ---------------------------------------------------------------------------------------------
# Lectura


def _text(data: Record, key: str, where: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"{where}: falta el texto «{key}»")
    return value


def _opt_text(data: Record, key: str, where: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise SchemaError(f"{where}: «{key}» debe ser texto")
    return value


def _flag(data: Record, key: str, where: str) -> bool:
    value = data.get(key, False)
    if not isinstance(value, bool):
        raise SchemaError(f"{where}: «{key}» debe ser verdadero o falso")
    return value


def _names(data: Record, key: str, where: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(
        isinstance(v, str) for v in cast(list[object], value)
    ):
        raise SchemaError(f"{where}: «{key}» debe ser una lista de textos")
    return tuple(cast(list[str], value))


def _records(data: Record, key: str, where: str) -> list[Record]:
    value = data.get(key, [])
    if not isinstance(value, list):
        raise SchemaError(f"{where}: «{key}» debe ser una lista")
    items = cast(list[object], value)
    if not all(isinstance(v, dict) for v in items):
        raise SchemaError(f"{where}: cada elemento de «{key}» debe ser una tabla")
    return cast(list[Record], items)


def _column(data: Record, where: str, *, comun: bool = False) -> Column:
    name = _text(data, "nombre", where)
    here = f"{where}.{name}"
    return Column(
        nombre=name,
        tipo=_text(data, "tipo", here),
        nulo=_flag(data, "nulo", here),
        unidad=_opt_text(data, "unidad", here),
        descripcion=_text(data, "descripcion", here),
        origen=_text(data, "origen", here),
        regla=_opt_text(data, "regla", here),
        comun=comun,
    )


def _foreign_key(data: Record, where: str) -> ForeignKey:
    return ForeignKey(
        columnas=_names(data, "columnas", where),
        referencia=_text(data, "referencia", where),
        referidas=_names(data, "referidas", where),
        opcional=_flag(data, "opcional", where),
        uno_a_uno=_flag(data, "uno_a_uno", where),
        nota=_opt_text(data, "nota", where),
    )


def _lists(data: Record, key: str, where: str) -> tuple[tuple[str, ...], ...]:
    value = data.get(key, [])
    if not isinstance(value, list):
        raise SchemaError(f"{where}: «{key}» debe ser una lista de listas")
    result: list[tuple[str, ...]] = []
    for item in cast(list[object], value):
        if not isinstance(item, list) or not all(
            isinstance(v, str) for v in cast(list[object], item)
        ):
            raise SchemaError(f"{where}: cada elemento de «{key}» debe ser una lista de textos")
        result.append(tuple(cast(list[str], item)))
    return tuple(result)


def _commons(raw: Record) -> dict[str, tuple[Column, str]]:
    section = raw.get("comunes", {})
    if not isinstance(section, dict):
        raise SchemaError("[comunes] debe ser una tabla")
    result: dict[str, tuple[Column, str]] = {}
    for name, value in cast(dict[str, object], section).items():
        if not isinstance(value, dict):
            raise SchemaError(f"comunes.{name} debe ser una tabla")
        entry = cast(Record, value)
        column = _column({"nombre": name, **entry}, "comunes", comun=True)
        result[name] = (column, _text(entry, "referencia", f"comunes.{name}"))
    return result


def _table(data: Record, commons: dict[str, tuple[Column, str]]) -> Table:
    where = f"{_text(data, 'esquema', 'tabla')}.{_text(data, 'nombre', 'tabla')}"
    own = [_column(c, where) for c in _records(data, "columnas", where)]
    chosen = _names(data, "comunes", where) if "comunes" in data else tuple(commons)
    unknown = [n for n in chosen if n not in commons]
    if unknown:
        raise SchemaError(f"{where}: columnas comunes desconocidas {unknown}")
    common_columns = [commons[n][0] for n in chosen]
    common_keys = [
        ForeignKey(
            (n,), commons[n][1], (n,), opcional=False, uno_a_uno=False, nota=None, comun=True
        )
        for n in chosen
    ]
    return Table(
        esquema=_text(data, "esquema", where),
        nombre=_text(data, "nombre", where),
        descripcion=_text(data, "descripcion", where),
        grano=_text(data, "grano", where),
        origen=_text(data, "origen", where),
        fuente=_text(data, "fuente", where),
        filas_dev16=_text(data, "filas_dev16", where),
        cegado=_text(data, "cegado", where),
        propuesta=_flag(data, "propuesta", where),
        excepcion=_opt_text(data, "excepcion_solo_agregar", where),
        visible_porque=_opt_text(data, "visible_porque", where),
        columnas=(*own, *common_columns),
        clave_primaria=_names(data, "clave_primaria", where),
        claves_foraneas=(
            *(_foreign_key(k, where) for k in _records(data, "claves_foraneas", where)),
            *common_keys,
        ),
        unicas=_lists(data, "unicas", where),
        reglas=tuple(
            Rule(
                _text(r, "nombre", where),
                _opt_text(r, "sql", where) or "",
                _text(r, "descripcion", where),
            )
            for r in _records(data, "reglas", where)
        ),
        indices=_lists(data, "indices", where),
    )


def load(path: Path) -> Design:
    """El diseño de ``path`` (``docs/bd/esquema.toml``).

    Raises:
        SchemaError: si falta un dato o no tiene la forma esperada.
        tomllib.TOMLDecodeError: si el archivo no es TOML válido.
    """
    with path.open("rb") as stream:
        raw = cast(Record, tomllib.load(stream))
    commons = _commons(raw)
    return Design(
        version=_text(raw, "version", "raíz"),
        fecha=_text(raw, "fecha", "raíz"),
        motor=_text(raw, "motor", "raíz"),
        estado=_text(raw, "estado", "raíz"),
        esquemas=tuple(
            (_text(s, "nombre", "esquemas"), _text(s, "descripcion", "esquemas"))
            for s in _records(raw, "esquemas", "raíz")
        ),
        tipos={
            _text(t, "nombre", "tipos"): (
                _text(t, "base", "tipos"),
                _text(t, "regla", "tipos"),
                _text(t, "descripcion", "tipos"),
            )
            for t in _records(raw, "tipos", "raíz")
        },
        roles=tuple(
            (
                _text(r, "nombre", "roles"),
                _text(r, "descripcion", "roles"),
                _text(r, "permisos", "roles"),
            )
            for r in _records(raw, "roles", "raíz")
        ),
        funciones=tuple(
            (
                _text(f, "nombre", "funciones"),
                _text(f, "clase", "funciones"),
                _text(f, "descripcion", "funciones"),
            )
            for f in _records(raw, "funciones", "raíz")
        ),
        vistas=tuple(
            (
                _text(v, "nombre", "vistas"),
                _text(v, "descripcion", "vistas"),
                _names(v, "fuentes", "vistas"),
            )
            for v in _records(raw, "vistas", "raíz")
        ),
        tablas=tuple(_table(t, commons) for t in _records(raw, "tablas", "raíz")),
    )


# ---------------------------------------------------------------------------------------------
# Verificación


@dataclass
class _Findings:
    errors: list[str] = field(default_factory=list[str])

    def add(self, where: str, message: str) -> None:
        self.errors.append(f"{where}: {message}")


def _check_columns(table: Table, design: Design, found: _Findings) -> None:
    seen: set[str] = set()
    for column in table.columnas:
        if not NAME.match(column.nombre):
            found.add(table.full, f"nombre de columna inválido «{column.nombre}»")
        if column.nombre in seen:
            found.add(table.full, f"columna repetida «{column.nombre}»")
        seen.add(column.nombre)
        if column.tipo not in BASE_TYPES and column.tipo not in design.tipos:
            found.add(table.full, f"tipo desconocido «{column.tipo}» en {column.nombre}")


def _check_keys(table: Table, found: _Findings) -> None:
    if not table.clave_primaria:
        found.add(table.full, "no tiene clave primaria")
    for name in table.clave_primaria:
        column = table.column(name)
        if column is None:
            found.add(table.full, f"la clave primaria usa una columna inexistente «{name}»")
        elif column.nulo:
            found.add(table.full, f"la columna de clave primaria «{name}» no puede quedar vacía")
    for group in (*table.unicas, *table.indices):
        for name in group:
            if table.column(name) is None:
                found.add(table.full, f"índice o clave única con columna inexistente «{name}»")


def _check_foreign_key(table: Table, key: ForeignKey, design: Design, found: _Findings) -> None:
    target = design.table(key.referencia)
    where = f"{table.full} -> {key.referencia}"
    if target is None:
        found.add(where, "la tabla referida no existe")
        return
    if len(key.columnas) != len(key.referidas):
        found.add(where, "distinta cantidad de columnas a cada lado")
        return
    if key.referidas != target.clave_primaria and key.referidas not in target.unicas:
        found.add(
            where,
            f"{key.referidas} no es la clave primaria ni una clave única de la tabla referida",
        )
    local = [table.column(n) for n in key.columnas]
    for name, column, other in zip(key.columnas, local, key.referidas, strict=True):
        remote = target.column(other)
        if column is None or remote is None:
            found.add(where, f"columna inexistente en {name} -> {other}")
        elif column.tipo != remote.tipo:
            found.add(where, f"tipos distintos: {name} {column.tipo} y {other} {remote.tipo}")
    nullable = any(c is not None and c.nulo for c in local)
    if key.opcional != nullable:
        found.add(where, "«opcional» no coincide con que sus columnas puedan quedar vacías")
    if key.uno_a_uno and key.columnas != table.clave_primaria:
        found.add(where, "una relación uno a uno debe usar toda la clave primaria")


def _has_key(table: Table, columns: tuple[str, ...], target: str) -> bool:
    return any(k.columnas == columns and k.referencia == target for k in table.claves_foraneas)


def _check_root(table: Table, kind: str, arg: str, found: _Findings) -> None:
    column = table.column(arg)
    if column is None:
        found.add(table.full, f"cegado por una columna inexistente «{arg}»")
        return
    if (kind == "raiz") == column.nulo:
        found.add(
            table.full, "la raíz del cegado debe ser obligatoria (u opcional con raiz_opcional)"
        )
    is_scenario_table = table.full == SCENARIOS and table.clave_primaria == (arg,)
    if not is_scenario_table and not _has_key(table, (arg,), SCENARIOS):
        found.add(table.full, f"«{arg}» debe ser clave foránea a {SCENARIOS}")


def _check_parent(table: Table, arg: str, design: Design, found: _Findings) -> None:
    match = PARENT.match(arg)
    if match is None:
        found.add(table.full, f"cegado por padre mal escrito «{arg}»")
        return
    parent = design.table(match[1])
    columns = tuple(match[2].split(","))
    if parent is None or parent.cegado == "no":
        found.add(table.full, f"el padre del cegado «{match[1]}» no existe o no está cegado")
    if not _has_key(table, columns, match[1]):
        found.add(table.full, f"falta la clave foránea {columns} a {match[1]}")


def _check_opening(table: Table, kind: str, arg: str, found: _Findings) -> None:
    columns = tuple(arg.split(","))
    if any(table.column(c) is None for c in columns):
        found.add(table.full, f"cegado por columnas inexistentes {columns}")
        return
    if kind == "apertura_particion":
        if len(columns) != APERTURA_PARTICION_ARGS or not _has_key(table, columns[:1], PARTITIONS):
            found.add(
                table.full, "apertura_particion necesita particion_id (clave foránea) y asignacion"
            )
    elif not _has_key(table, columns, EXPERIMENTS):
        found.add(table.full, f"apertura_experimento necesita clave foránea a {EXPERIMENTS}")


def _check_blinding(  # noqa: PLR0912 (validación de cada tipo de cegado)
    table: Table, design: Design, found: _Findings
) -> None:
    kind, _, arg = table.cegado.partition(":")
    if kind == "no" and not arg:
        return
    if kind in ("raiz", "raiz_opcional"):
        _check_root(table, kind, arg, found)
    elif kind == "padre":
        _check_parent(table, arg, design, found)
    elif kind in ("apertura_particion", "apertura_experimento"):
        _check_opening(table, kind, arg, found)
    elif kind == "archivo_alcance" and table.full == "control.artefactos":
        if table.column("alcance") is None:
            found.add(table.full, "el cegado de archivos necesita la columna alcance")
    elif kind == "archivo_enlace" and table.full == "control.archivo_escenarios":
        if not _has_key(table, ("artefacto_id",), "control.artefactos"):
            found.add(table.full, "el enlace debe referir a un archivo")
    elif kind == "uso_plan" and table.full == "simulacion.planes":
        pass  # las referencias de uso se construyen desde las claves foráneas en ddl.py
    elif kind == "ambas_corridas" and table.full == "control.replicas":
        for column in ("run_id_a", "run_id_b"):
            if not _has_key(table, (column,), "simulacion.corridas"):
                found.add(table.full, f"falta la clave foránea de {column} a corridas")
    elif kind == "ambas_comparaciones" and table.full == "evaluacion.diferencias":
        for column in ("comparacion_a_id", "comparacion_b_id"):
            if not _has_key(table, (column,), "evaluacion.comparaciones"):
                found.add(table.full, f"falta la clave foránea de {column} a comparaciones")
    else:
        found.add(table.full, f"cegado desconocido «{table.cegado}»")


def _check_blinded_links(table: Table, design: Design, found: _Findings) -> None:
    """Una relación con datos cegados exige cegado propio o una razón escrita."""
    if table.cegado != "no" or table.visible_porque:
        return
    for key in table.claves_foraneas:
        if key.comun:
            continue  # la excepción de procedencia está escrita en [comunes].artefacto_id
        target = design.table(key.referencia)
        if target is not None and target.cegado != "no":
            found.add(
                table.full,
                f"referencia {target.full} cegada: declare cegado o visible_porque",
            )


def verify(design: Design, catalog: set[str]) -> list[str]:
    """Los problemas del diseño; lista vacía si es correcto.

    ``catalog`` son los nombres de las tablas aprobadas (catálogo del acta de DEV31 F0): las
    tablas no marcadas como propuesta deben coincidir exactamente con ellos.
    """
    found = _Findings()
    schemas = {name for name, _ in design.esquemas}
    seen: set[str] = set()
    for table in design.tablas:
        if table.esquema not in schemas:
            found.add(table.full, "esquema no declarado")
        if not NAME.match(table.nombre) or table.nombre in seen:
            found.add(table.full, "nombre de tabla inválido o repetido")
        seen.add(table.nombre)
        _check_columns(table, design, found)
        _check_keys(table, found)
        for key in table.claves_foraneas:
            _check_foreign_key(table, key, design, found)
        _check_blinding(table, design, found)
        _check_blinded_links(table, design, found)
    approved = {t.nombre for t in design.tablas if not t.propuesta}
    if approved != catalog:
        found.add(
            "catálogo del acta F0",
            f"faltan {sorted(catalog - approved)}; sobran {sorted(approved - catalog)}",
        )
    return found.errors
