"""Huella de contenido de la base y huellas de lo publicado en git (DEV31 F3; QA36 y ADR03).

- ``content_hash``: una huella SHA-256 de **todo** el contenido de la base, tabla por tabla y fila
  por fila, en un orden fijo. Si la base se borra y se regenera desde los mismos archivos, la
  huella sale igual (QA36). Se dejan fuera solo los datos propios de cada carga, que cambian aunque
  los archivos sean los mismos: las tablas ``control.cargas`` y ``control.conflictos``, la columna
  ``carga_id`` de todas las tablas y la fecha de registro de cada archivo.
- ``root_fingerprints``: la huella de cada archivo «raíz» que conoce la base (un manifiesto, o un
  archivo suelto como el caso o un protocolo). La huella de un manifiesto fija la de todos los
  archivos que declara, así que con estas huellas se puede comprobar todo lo publicado.
- ``write_fingerprints``: guarda esas huellas y la huella de contenido en un archivo de texto del
  repositorio (por ejemplo ``docs/bd/huellas.json``). Al confirmarlo en git y subirlo a GitHub,
  queda una fecha externa que el administrador de la laptop no puede cambiar (ADR03).
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from psycopg import sql

from semaforo.bd.carga.insercion import Catalog, TableInfo
from semaforo.bd.carga.modelo import DATA_ROOT, REPOSITORY_ROOT
from semaforo.bd.conexion import Connection
from semaforo.dominio.base_model import FrozenModel
from semaforo.trazabilidad.hashing import sha256_file

__all__ = [
    "EXCLUDED_TABLES",
    "Fingerprint",
    "FingerprintFile",
    "RootCheck",
    "check_roots",
    "content_hash",
    "root_fingerprints",
    "write_fingerprints",
]

EXCLUDED_TABLES = frozenset({"control.cargas", "control.conflictos"})
EXCLUDED_COLUMNS = frozenset({"carga_id"})
VOLATILE = {"control.artefactos": frozenset({"registrado_en"})}
COLLATABLE = frozenset({"text", "control.huella"})


def _columns(info: TableInfo) -> list[str]:
    skip = EXCLUDED_COLUMNS | VOLATILE.get(info.full, frozenset())
    return [column for column in info.columns if column not in skip]


def _order(info: TableInfo) -> sql.Composed:
    """La clave primaria como orden, con la intercalación «C» en los textos: el orden no depende
    del idioma configurado en el servidor."""
    parts = [
        sql.SQL('{} COLLATE "C"').format(sql.Identifier(column))
        if info.types[column] in COLLATABLE
        else sql.SQL("{}").format(sql.Identifier(column))
        for column in info.primary
    ]
    return sql.SQL(", ").join(parts)


def content_hash(connection: Connection, catalog: Catalog) -> tuple[str, dict[str, int]]:
    """La huella de contenido de la base y las filas de cada tabla que entran en ella.

    Lee con ``COPY`` en texto, con la zona horaria UTC y el formato de fechas ISO, para que los
    mismos datos den siempre los mismos bytes.
    """
    digest = hashlib.sha256()
    rows: dict[str, int] = {}
    with connection.transaction():
        connection.execute("SET LOCAL TimeZone = 'UTC'")
        connection.execute("SET LOCAL DateStyle = 'ISO, YMD'")
        connection.execute("SET LOCAL extra_float_digits = 1")
        for name in sorted(catalog.tables):
            if name in EXCLUDED_TABLES:
                continue
            info = catalog.tables[name]
            columns = sql.SQL(", ").join(map(sql.Identifier, _columns(info)))
            digest.update(f"\n== {name}\n".encode())
            count = 0
            query = sql.SQL("COPY (SELECT {} FROM {} ORDER BY {}) TO STDOUT").format(
                columns, info.identifier, _order(info)
            )
            with connection.cursor() as cursor, cursor.copy(query) as copy:
                for block in copy:
                    data = bytes(block)
                    digest.update(data)
                    count += data.count(b"\n")
            rows[name] = count
    return digest.hexdigest(), rows


class Fingerprint(FrozenModel):
    """Un archivo raíz con su huella."""

    artefacto_id: str
    sha256: str


class FingerprintFile(FrozenModel):
    """El archivo de huellas que se guarda en git (ADR03)."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    generated_at: datetime
    carga_id: str | None
    schema_version_db: str | None
    content_sha256: str
    rows: dict[str, int]
    roots: list[Fingerprint]


def root_fingerprints(connection: Connection) -> list[Fingerprint]:
    """Los archivos raíz íntegros que conoce la base, ordenados."""
    return [
        Fingerprint(artefacto_id=str(identifier), sha256=str(digest))
        for identifier, digest in connection.execute(
            "SELECT artefacto_id, sha256 FROM control.artefactos "
            "WHERE manifiesto_id IS NULL AND estado = 'intact' "
            'ORDER BY artefacto_id COLLATE "C"'
        )
    ]


def _render(document: FingerprintFile) -> bytes:
    """JSON legible y estable: una línea por archivo raíz (los cambios se ven bien en git)."""
    head = document.model_dump(mode="json", exclude={"roots"})
    lines = [json.dumps(head, ensure_ascii=False, indent=2)[:-2] + ","]
    lines.append('  "roots": [')
    roots = [
        "    " + json.dumps(root.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
        for root in document.roots
    ]
    lines.append(",\n".join(roots))
    lines.append("  ]\n}\n")
    return "\n".join(lines).encode("utf-8")


def write_fingerprints(path: Path, document: FingerprintFile) -> None:
    """Escribe ``path`` de una vez (temporal y renombrado)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(_render(document))
    temporary.replace(path)


class RootCheck(FrozenModel):
    """Un archivo raíz que ya no coincide con la base (o que no se encuentra)."""

    artefacto_id: str
    expected_sha256: str
    found_sha256: str | None


def check_roots(
    connection: Connection, workspace: Path, repository: Path | None
) -> tuple[int, list[RootCheck]]:
    """Vuelve a calcular la huella de cada archivo raíz y devuelve los que no coinciden.

    Los de ``repositorio:`` (las actas de los hitos) solo se revisan si se indica la carpeta del
    repositorio.
    """
    roots = root_fingerprints(connection)
    bases = {DATA_ROOT: workspace, REPOSITORY_ROOT: repository}
    checked = 0
    problems: list[RootCheck] = []
    for root in roots:
        prefix, _, relative = root.artefacto_id.partition(":")
        base = bases.get(prefix)
        if base is None:
            continue
        checked += 1
        path = base / relative
        found = sha256_file(path) if path.is_file() and not path.is_symlink() else None
        if found != root.sha256:
            problems.append(
                RootCheck(
                    artefacto_id=root.artefacto_id, expected_sha256=root.sha256, found_sha256=found
                )
            )
    return checked, problems
