"""Huella de las reglas instaladas en la base (DEV31 F4c, C1.10; hallazgo N3 de la auditoría).

La huella de contenido (``verificacion``) solo mira las filas. Si alguien apaga un disparador, borra
una política de cegado o cambia un permiso **sin tocar ninguna fila**, esa huella y la versión
declarada del esquema siguen iguales. Esta huella mira lo que **está instalado y activo** en la
base, leído de su catálogo:

- disparadores y si están activos;
- seguridad por filas y sus políticas;
- permisos de tablas, vistas, esquemas, funciones y de la propia base;
- definiciones de funciones y de vistas;
- restricciones (claves, comprobaciones) e índices;
- los atributos de los usuarios del proyecto.

Sale igual en dos bases con el mismo esquema (no usa números internos de PostgreSQL), así que sirve
también para comprobar que una base de pruebas tiene las mismas reglas que la base en uso.
"""

import hashlib
from dataclasses import dataclass

from semaforo.bd.conexion import ROLES, Connection

__all__ = ["RULES_ALGORITHM", "SCHEMAS", "rules_digest"]

RULES_ALGORITHM = "reglas-2"  # 2: también el usuario del panel
SCHEMAS = ["control", "caso", "experimento", "simulacion", "aprendizaje", "evaluacion", "vistas"]
SEPARATOR = "\x1f"


@dataclass(frozen=True)
class _Section:
    name: str
    query: str
    parameters: tuple[object, ...]


def _sections() -> list[_Section]:
    schemas = (SCHEMAS,)
    return [
        _Section(
            "disparadores",
            "SELECT n.nspname || '.' || c.relname, t.tgname, t.tgenabled::text, "
            "pg_get_triggerdef(t.oid) FROM pg_trigger AS t "
            "JOIN pg_class AS c ON c.oid = t.tgrelid "
            "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE NOT t.tgisinternal AND n.nspname = ANY(%s) ORDER BY 1, 2",
            schemas,
        ),
        _Section(
            "seguridad por filas",
            "SELECT n.nspname || '.' || c.relname, c.relrowsecurity::text, "
            "c.relforcerowsecurity::text FROM pg_class AS c "
            "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE c.relkind IN ('r', 'p') AND n.nspname = ANY(%s) ORDER BY 1",
            schemas,
        ),
        _Section(
            "políticas",
            "SELECT schemaname || '.' || tablename, policyname, permissive, "
            "(SELECT string_agg(r, ',' ORDER BY r) FROM unnest(roles) AS r), cmd, "
            "coalesce(qual, ''), coalesce(with_check, '') FROM pg_policies "
            "WHERE schemaname = ANY(%s) ORDER BY 1, 2",
            schemas,
        ),
        _Section(
            "permisos de tablas y vistas",
            "SELECT n.nspname || '.' || c.relname, c.relkind::text, "
            "coalesce((SELECT string_agg(a::text, ',' ORDER BY a::text) "
            "FROM unnest(c.relacl) AS a), '') "
            "FROM pg_class AS c JOIN pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE n.nspname = ANY(%s) AND c.relkind IN ('r', 'p', 'v', 'm', 'S') ORDER BY 1",
            schemas,
        ),
        _Section(
            "permisos de esquemas",
            "SELECT nspname, coalesce((SELECT string_agg(a::text, ',' ORDER BY a::text) "
            "FROM unnest(nspacl) AS a), '') FROM pg_namespace "
            "WHERE nspname = ANY(%s) ORDER BY 1",
            schemas,
        ),
        _Section(
            "permisos de la base",
            "SELECT 'base', coalesce((SELECT string_agg(a::text, ',' ORDER BY a::text) "
            "FROM unnest(datacl) AS a), '') FROM pg_database "
            "WHERE datname = current_database()",
            (),
        ),
        _Section(
            "funciones",
            "SELECT n.nspname || '.' || p.proname || '(' || "
            "pg_get_function_identity_arguments(p.oid) || ')', p.prosecdef::text, "
            "coalesce((SELECT string_agg(a::text, ',' ORDER BY a::text) "
            "FROM unnest(p.proacl) AS a), ''), pg_get_functiondef(p.oid) FROM pg_proc AS p "
            "JOIN pg_namespace AS n ON n.oid = p.pronamespace "
            "WHERE n.nspname = ANY(%s) AND p.prokind = 'f' ORDER BY 1",
            schemas,
        ),
        _Section(
            "vistas",
            "SELECT n.nspname || '.' || c.relname, coalesce(c.reloptions::text, ''), "
            "pg_get_viewdef(c.oid) FROM pg_class AS c "
            "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE c.relkind = 'v' AND n.nspname = ANY(%s) ORDER BY 1",
            schemas,
        ),
        _Section(
            "restricciones",
            "SELECT n.nspname || '.' || c.relname, k.conname, k.contype::text, "
            "pg_get_constraintdef(k.oid), k.convalidated::text FROM pg_constraint AS k "
            "JOIN pg_class AS c ON c.oid = k.conrelid "
            "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE n.nspname = ANY(%s) ORDER BY 1, 2",
            schemas,
        ),
        _Section(
            "índices",
            "SELECT schemaname || '.' || tablename, indexname, indexdef FROM pg_indexes "
            "WHERE schemaname = ANY(%s) ORDER BY 1, 2",
            schemas,
        ),
        _Section(
            "usuarios del proyecto",
            "SELECT rolname, rolsuper::text, rolcreatedb::text, rolcreaterole::text, "
            "rolcanlogin::text, rolbypassrls::text, rolreplication::text FROM pg_roles "
            "WHERE rolname = ANY(%s) ORDER BY 1",
            (list(ROLES),),
        ),
    ]


def rules_digest(connection: Connection) -> tuple[str, dict[str, int]]:
    """La huella de las reglas instaladas y cuántos elementos tiene cada sección.

    Fija ``search_path`` en ``pg_catalog`` mientras lee (las definiciones de PostgreSQL calificarían
    los nombres según el ``search_path`` de quien las pide) y lo deja como estaba.
    """
    digest = hashlib.sha256()
    counts: dict[str, int] = {}
    with connection.transaction():
        previous = connection.execute("SHOW search_path").fetchone()
        connection.execute("SELECT set_config('search_path', 'pg_catalog', true)")
        for section in _sections():
            digest.update(f"\n== {section.name}\n".encode())
            rows = connection.execute(section.query.encode(), section.parameters).fetchall()
            counts[section.name] = len(rows)
            for row in rows:
                line = SEPARATOR.join("" if cell is None else str(cell) for cell in row)
                digest.update(line.encode())
                digest.update(b"\n")
        connection.execute(
            "SELECT set_config('search_path', %s, true)",
            ("" if previous is None else str(previous[0]),),
        )
    return digest.hexdigest(), counts
