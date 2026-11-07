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
from dataclasses import dataclass
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
    "HASH_ALGORITHM",
    "Fingerprint",
    "FingerprintFile",
    "Measured",
    "ReferenceCheck",
    "ReferenceDifference",
    "RootCheck",
    "check_roots",
    "compare_with_reference",
    "content_hash",
    "read_fingerprints",
    "root_fingerprints",
    "write_fingerprints",
]

# Versión del algoritmo de la huella de contenido (D13): cambia si cambia qué tablas, columnas,
# orden o formato entran en ella. Una referencia con otro algoritmo no se puede comparar.
HASH_ALGORITHM = "contenido-1"
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
    """El archivo de huellas que se guarda en git (ADR03).

    La versión 1.1.0 agrega la versión del algoritmo de la huella de contenido (D13), la huella de
    las reglas instaladas y la versión de su algoritmo. Un archivo 1.0.0 (sin esos campos) se lee
    igual: su algoritmo es el de siempre (``contenido-1``) y no tiene huella de reglas.
    """

    schema_version: Literal["1.0.0", "1.1.0"] = "1.1.0"
    generated_at: datetime
    carga_id: str | None
    schema_version_db: str | None
    content_sha256: str
    algoritmo_huella: str | None = None
    reglas_sha256: str | None = None
    algoritmo_reglas: str | None = None
    rows: dict[str, int]
    roots: list[Fingerprint]


class ReferenceDifference(FrozenModel):
    """Una cosa que cambió respecto de la referencia: qué, y los dos valores."""

    item: str
    reference: str
    database: str


class ReferenceCheck(FrozenModel):
    """El resultado de comparar la base con una huella de referencia (C1.6)."""

    source: str
    outcome: Literal["coincide", "difiere", "no_concluyente"]
    reason: str | None
    differences: list[ReferenceDifference]


@dataclass(frozen=True)
class Measured:
    """Lo que midió la verificación en la base."""

    schema_version: str | None
    content_sha256: str
    rules_sha256: str
    rows: dict[str, int]
    roots: list[Fingerprint]


def compare_with_reference(
    reference: FingerprintFile, measured: Measured, source: str
) -> ReferenceCheck:
    """Compara lo medido con la referencia. Una referencia de otra versión no es comparable.

    - otra versión del esquema, o del algoritmo de la huella: *no concluyente* (no es una
      diferencia: no se puede decir si algo cambió);
    - igual versión: *difiere* si cambia la huella de contenido, alguna tabla, algún archivo raíz
      o la huella de las reglas; si no, *coincide*. Una referencia sin huella de reglas (1.0.0) no
      dice nada de las reglas.
    """
    if reference.schema_version_db != measured.schema_version:
        return ReferenceCheck(
            source=source,
            outcome="no_concluyente",
            reason=(
                f"la referencia es de otra versión del esquema ({reference.schema_version_db}); "
                f"la base tiene {measured.schema_version}"
            ),
            differences=[],
        )
    algorithm = reference.algoritmo_huella or HASH_ALGORITHM
    if algorithm != HASH_ALGORITHM:
        return ReferenceCheck(
            source=source,
            outcome="no_concluyente",
            reason=(
                f"contenido no comprobado: algoritmo distinto ({algorithm}; ahora {HASH_ALGORITHM})"
            ),
            differences=[],
        )
    found: list[ReferenceDifference] = []
    if reference.content_sha256 != measured.content_sha256:
        found.append(
            ReferenceDifference(
                item="huella de contenido",
                reference=reference.content_sha256,
                database=measured.content_sha256,
            )
        )
    for table in sorted(set(reference.rows) | set(measured.rows)):
        before, now = reference.rows.get(table), measured.rows.get(table)
        if before != now:
            found.append(
                ReferenceDifference(
                    item=f"filas de {table}", reference=str(before), database=str(now)
                )
            )
    expected = {root.artefacto_id: root.sha256 for root in reference.roots}
    current = {root.artefacto_id: root.sha256 for root in measured.roots}
    for identifier in sorted(set(expected) | set(current)):
        if expected.get(identifier) != current.get(identifier):
            found.append(
                ReferenceDifference(
                    item=f"archivo raíz {identifier}",
                    reference=str(expected.get(identifier)),
                    database=str(current.get(identifier)),
                )
            )
    if reference.reglas_sha256 is not None and reference.reglas_sha256 != measured.rules_sha256:
        found.append(
            ReferenceDifference(
                item="reglas instaladas",
                reference=reference.reglas_sha256,
                database=measured.rules_sha256,
            )
        )
    return ReferenceCheck(
        source=source,
        outcome="difiere" if found else "coincide",
        reason=None,
        differences=found,
    )


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


def read_fingerprints(text: str) -> FingerprintFile:
    """El archivo de huellas a partir de su texto (por ejemplo, el que está en git).

    Raises:
        ValueError: si el texto no es un archivo de huellas válido.
    """
    return FingerprintFile.model_validate_json(text)


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
