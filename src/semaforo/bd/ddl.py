"""El SQL que crea la base, generado desde el diseño (DEV31 F3).

Dos de los tres archivos de ``semaforo/bd/sql`` salen de aquí; el del medio se escribe a mano:

1. ``01_tablas.sql``: esquemas, el tipo ``huella``, las tablas con sus columnas, claves, reglas
   (``CHECK``), relaciones e índices, y sus descripciones como comentarios de la base;
2. ``02_reglas.sql`` (a mano): las funciones y disparadores con lógica (orden de los hitos,
   asignaciones, corridas finales, conjuntos), los índices parciales de los hitos y las vistas;
3. ``03_seguridad.sql``: el disparador de «solo agregar» en cada tabla, el cegado de la prueba con
   seguridad por filas y los permisos de los usuarios.

El texto generado es siempre el mismo para el mismo diseño: ``scripts/bd_esquema.py --comprobar``
falla si los archivos publicados no están al día.
"""

import re

from semaforo.bd.diseno import BASE_TYPES, Design, ForeignKey, Table

__all__ = [
    "CARGA",
    "LECTURA",
    "MAX_NAME",
    "VIEWS_SCHEMA",
    "blinding_expression",
    "security_sql",
    "tables_sql",
]

CARGA = "semaforo_carga"
LECTURA = "semaforo_lectura"
PANEL = "semaforo_panel"
PANEL_VIEWS = (
    "zona_escenario",
    "estado_hitos",
    "corridas_resumen",
    "vehiculos_cohorte",
    "cola_por_segundo",
    "busquedas_resumen",
    "etiquetas_entrenamiento",
    "metricas_modelos",
    "consultas_resumen",
    "indicadores_finales",
)
VIEWS_SCHEMA = "vistas"
MAX_NAME = 63  # largo máximo de un nombre en PostgreSQL
DOMAIN_SCHEMA = "control"
DEFERRABLE_MARK = "Diferible"
IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*")
HEADER = (
    "-- Archivo generado por scripts/bd_esquema.py desde docs/bd/esquema.toml (versión {version})."
    "\n-- No se edita a mano: se cambia el esquema y se vuelve a generar.\n"
)


def _literal(text: str) -> str:
    """Texto como literal SQL entre comillas simples."""
    return "'" + text.replace("'", "''") + "'"


def _name(text: str) -> str:
    if len(text) > MAX_NAME:
        raise ValueError(f"nombre demasiado largo para PostgreSQL: {text}")
    return text


def _type(design: Design, tipo: str) -> str:
    if tipo in BASE_TYPES:
        return tipo
    if tipo in design.tipos:
        return f"{DOMAIN_SCHEMA}.{tipo}"
    raise ValueError(f"tipo desconocido: {tipo}")


def _columns(names: tuple[str, ...]) -> str:
    return ", ".join(names)


def _table(design: Design, table: Table) -> list[str]:
    lines = [
        f"    {c.nombre} {_type(design, c.tipo)}{'' if c.nulo else ' NOT NULL'}"
        for c in table.columnas
    ]
    lines.append(
        f"    CONSTRAINT {_name(table.nombre + '_pk')} PRIMARY KEY "
        f"({_columns(table.clave_primaria)})"
    )
    for number, group in enumerate(table.unicas, start=1):
        lines.append(
            f"    CONSTRAINT {_name(f'{table.nombre}_unica_{number}')} UNIQUE ({_columns(group)})"
        )
    for column in table.columnas:
        if column.regla:
            name = _name(f"{table.nombre}_{column.nombre}_regla")
            lines.append(f"    CONSTRAINT {name} CHECK ({column.regla})")
    for rule in table.reglas:
        if rule.sql:
            lines.append(
                f"    CONSTRAINT {_name(f'{table.nombre}_{rule.nombre}')} CHECK ({rule.sql})"
            )
    out = [f"CREATE TABLE {table.full} (", ",\n".join(lines), ");"]
    out.append(f"COMMENT ON TABLE {table.full} IS {_literal(table.descripcion)};")
    for column in table.columnas:
        text = column.descripcion + (f" Unidad: {column.unidad}." if column.unidad else "")
        out.append(f"COMMENT ON COLUMN {table.full}.{column.nombre} IS {_literal(text)};")
    return out


def _foreign_key(table: Table, number: int, key: ForeignKey) -> str:
    deferrable = (
        " DEFERRABLE INITIALLY DEFERRED" if key.nota and DEFERRABLE_MARK in key.nota else ""
    )
    name = _name(f"{table.nombre}_fk_{number}")
    return (
        f"ALTER TABLE {table.full} ADD CONSTRAINT {name} FOREIGN KEY ({_columns(key.columnas)}) "
        f"REFERENCES {key.referencia} ({_columns(key.referidas)}){deferrable};"
    )


def tables_sql(design: Design) -> str:
    """``01_tablas.sql``: esquemas, tipos, tablas, relaciones e índices."""
    _check_names(design)
    out = [HEADER.format(version=design.version)]
    for schema, description in (*design.esquemas, (VIEWS_SCHEMA, "Vistas del panel y consultas.")):
        out.append(f"CREATE SCHEMA {schema};")
        out.append(f"COMMENT ON SCHEMA {schema} IS {_literal(description)};")
    out.append("")
    for name, (base, rule, description) in design.tipos.items():
        out.append(f"CREATE DOMAIN {DOMAIN_SCHEMA}.{name} AS {base} CHECK ({rule});")
        out.append(f"COMMENT ON DOMAIN {DOMAIN_SCHEMA}.{name} IS {_literal(description)};")
    for table in design.tablas:
        out.append("")
        out.extend(_table(design, table))
    out.append("")
    out.append("-- Relaciones: se agregan al final para que el orden de las tablas no importe.")
    for table in design.tablas:
        out.extend(
            _foreign_key(table, number, key)
            for number, key in enumerate(table.claves_foraneas, start=1)
        )
    out.append("")
    for table in design.tablas:
        for group in table.indices:
            name = _name(f"{table.nombre}_ix_{'_'.join(group)}")
            out.append(f"CREATE INDEX {name} ON {table.full} ({_columns(group)});")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------------------------
# Seguridad


def _parent_key(table: Table, parent: str, columns: tuple[str, ...]) -> ForeignKey:
    for key in table.claves_foraneas:
        if key.referencia == parent and key.columnas == columns:
            return key
    raise ValueError(f"{table.full}: falta la relación con {parent}")


def blinding_expression(  # noqa: PLR0911, PLR0912 (cada tipo de cegado tiene su regla)
    table: Table, design: Design | None = None
) -> str | None:
    """La condición que deja ver una fila al usuario de lectura; ``None`` si no hay cegado.

    La zona no se guarda en las filas: se deduce de las asignaciones y los hitos (acta de F1).
    """
    # Los nombres que se insertan en el SQL salen del diseño y pasan por _check_names: no hay
    # texto de usuario (de ahí los noqa S608).
    kind, _, arg = table.cegado.partition(":")
    hidden = (
        "NOT EXISTS (SELECT 1 FROM control.escenarios_cegados AS cegado "  # noqa: S608
        f"WHERE cegado.escenario_id = {table.nombre}.{arg})"
    )
    if kind == "no":
        return None
    if kind == "archivo_alcance":
        return "control.archivo_visible(artefactos.artefacto_id)"
    if kind == "archivo_enlace":
        return "control.archivo_visible(archivo_escenarios.artefacto_id)"
    if kind == "ambas_corridas":
        return (
            "EXISTS (SELECT 1 FROM simulacion.corridas AS a "
            "WHERE a.run_id = replicas.run_id_a) AND "
            "EXISTS (SELECT 1 FROM simulacion.corridas AS b "
            "WHERE b.run_id = replicas.run_id_b)"
        )
    if kind == "ambas_comparaciones":
        return (
            "EXISTS (SELECT 1 FROM evaluacion.comparaciones AS a "
            "WHERE a.comparacion_id = diferencias.comparacion_a_id) AND "
            "EXISTS (SELECT 1 FROM evaluacion.comparaciones AS b "
            "WHERE b.comparacion_id = diferencias.comparacion_b_id)"
        )
    if kind == "uso_plan":
        if design is None:
            raise ValueError("el cegado de planes necesita el diseño de las relaciones")
        uses: list[str] = []
        for other in design.tablas:
            if other.full == "simulacion.plan_tramos":
                continue  # son los detalles del plan, no una mención visible de él
            for key in other.claves_foraneas:
                if key.referencia == "simulacion.planes":
                    uses.append(
                        f"EXISTS (SELECT 1 FROM {other.full} AS uso "  # noqa: S608
                        f"WHERE uso.{key.columnas[0]} = planes.plan_id)"
                    )
        return " OR ".join(uses)
    if kind == "raiz":
        return hidden
    if kind == "raiz_opcional":
        return f"{table.nombre}.{arg} IS NULL OR {hidden}"
    if kind == "padre":
        parent, _, inner = arg.partition("(")
        columns = tuple(inner.rstrip(")").split(","))
        key = _parent_key(table, parent, columns)
        joins = " AND ".join(
            f"padre.{remote} = {table.nombre}.{local}"
            for local, remote in zip(key.columnas, key.referidas, strict=True)
        )
        return f"EXISTS (SELECT 1 FROM {parent} AS padre WHERE {joins})"  # noqa: S608
    if kind == "apertura_particion":
        partition, assignment = arg.split(",")
        return (
            f"{table.nombre}.{assignment} <> 'test' "
            f"OR control.prueba_abierta({table.nombre}.{partition})"
        )
    if kind == "apertura_experimento":
        return (
            "EXISTS (SELECT 1 FROM control.hitos AS hito "  # noqa: S608
            f"WHERE hito.tipo = 'test_opened' AND hito.experimento_id = {table.nombre}.{arg})"
        )
    raise ValueError(f"{table.full}: cegado desconocido {table.cegado}")


def _check_names(design: Design) -> None:
    """Todo nombre que va al SQL es un identificador simple (minúsculas, cifras y guion bajo).

    ``semaforo.bd.diseno.verify`` ya lo exige; se repite aquí para que el SQL nunca reciba un
    texto que no sea un nombre, aunque alguien llame al generador sin verificar.
    """
    names: list[str] = [name for name, _ in design.esquemas]
    names += list(design.tipos)
    for table in design.tablas:
        names += [table.esquema, table.nombre, *(c.nombre for c in table.columnas)]
        for key in table.claves_foraneas:
            names += [*key.columnas, *key.referidas, *key.referencia.split(".")]
        names += [r.nombre for r in table.reglas]
        kind, _, arg = table.cegado.partition(":")
        names.append(kind)
        names += [part for part in re.split(r"[.,()]", arg) if part]
    bad = sorted({name for name in names if not IDENTIFIER.fullmatch(name)})
    if bad:
        raise ValueError(f"nombres que no son identificadores simples: {bad}")


def _updatable(design: Design) -> list[str]:
    return [t.full for t in design.tablas if t.excepcion]


def security_sql(design: Design) -> str:
    """``03_seguridad.sql``: solo agregar, cegado y permisos."""
    _check_names(design)
    out = [HEADER.format(version=design.version)]
    out.append("-- Solo agregar (B2): se rechazan la modificación, el borrado y el vaciado.")
    for table in design.tablas:
        out.append(
            f"CREATE TRIGGER solo_agregar BEFORE UPDATE OR DELETE ON {table.full} "
            "FOR EACH ROW EXECUTE FUNCTION control.bloquear_cambios();"
        )
        out.append(
            f"CREATE TRIGGER solo_agregar_vaciado BEFORE TRUNCATE ON {table.full} "
            "FOR EACH STATEMENT EXECUTE FUNCTION control.bloquear_cambios();"
        )
    out.append("")
    out.append("-- Cegado de la prueba (B4, con la zona deducida de F1): seguridad por filas.")
    for table in design.tablas:
        condition = blinding_expression(table, design)
        if condition is None:
            continue
        out.append(f"ALTER TABLE {table.full} ENABLE ROW LEVEL SECURITY;")
        out.append(
            f"CREATE POLICY carga_ve_todo ON {table.full} TO {CARGA} "
            "USING (true) WITH CHECK (true);"
        )
        out.append(
            f"CREATE POLICY lectura_cegada ON {table.full} FOR SELECT TO {LECTURA} "
            f"USING ({condition});"
        )
    schemas = ", ".join(name for name, _ in design.esquemas)
    out.append("")
    out.append("-- Permisos (roles del diseño). El dueño de todo es semaforo_admin.")
    out.append(f"GRANT USAGE ON SCHEMA {schemas} TO {CARGA};")
    out.append(f"GRANT USAGE ON SCHEMA {schemas}, {VIEWS_SCHEMA} TO {LECTURA};")
    out.append(f"GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA {schemas} TO {CARGA};")
    out.append(f"GRANT UPDATE ON {', '.join(_updatable(design))} TO {CARGA};")
    out.append(f"GRANT SELECT ON ALL TABLES IN SCHEMA {schemas}, {VIEWS_SCHEMA} TO {LECTURA};")
    out.append("")
    out.append(
        "-- El panel solo lee las vistas con filtro explícito de cegado, revisadas por separado."
    )
    out.append(f"GRANT USAGE ON SCHEMA {VIEWS_SCHEMA} TO {PANEL};")
    for name in PANEL_VIEWS:
        full = f"{VIEWS_SCHEMA}.{name}"
        if not any(view == full for view, _, _ in design.vistas):
            raise ValueError(f"vista del panel ausente del diseño: {full}")
        out.append(f"ALTER VIEW {full} SET (security_invoker = false);")
        out.append(f"GRANT SELECT ON {full} TO {PANEL};")
    return "\n".join(out) + "\n"
